# Deploy Checklist — AI Twin

Kurze Referenz für lokales Deploy und GitHub Actions. Basiert auf den tatsächlichen Stolpersteinen dieses Projekts.

---

## Schnell-Check vor jedem Deploy

| # | Check | Erwartung |
|---|--------|-----------|
| 1 | AWS CLI funktioniert | `aws sts get-caller-identity` liefert Account-ID |
| 2 | Region gesetzt | `DEFAULT_AWS_REGION=eu-central-1` (oder deine Region) |
| 3 | Lambda-Zip existiert | `backend/lambda-deployment.zip` (wird von `deploy.py` gebaut) |
| 4 | Terraform State Backend | S3 `twin-terraform-state-<ACCOUNT_ID>` + DynamoDB `twin-terraform-locks` |
| 5 | GitHub Secrets | `AWS_ROLE_ARN`, `AWS_ACCOUNT_ID`, `DEFAULT_AWS_REGION` |
| 6 | OIDC Trust Policy | `sub`-Claim aus GitHub passt zur IAM-Rolle (siehe unten) |
| 7 | Bedrock Model ID | `global.amazon.nova-2-lite-v1:0` (nicht `amazon.nova-lite-v1:0`) |

---

## Einmal-Setup (pro AWS-Account)

### 1. Terraform State Backend (S3 + DynamoDB)

**Datei:** `terraform/backend-setup.tf` — muss im Ordner `terraform/` liegen, **nicht** in `terraform/.terraform/`.

```bash
cd terraform
terraform workspace select default
terraform init

terraform apply \
  -target=aws_s3_bucket.terraform_state \
  -target=aws_s3_bucket_versioning.terraform_state \
  -target=aws_s3_bucket_server_side_encryption_configuration.terraform_state \
  -target=aws_s3_bucket_public_access_block.terraform_state \
  -target=aws_dynamodb_table.terraform_locks
```

Erwartung: **5 added**. Wenn „No changes“ ohne vorherigen Apply → Datei liegt vermutlich im falschen Ordner.

Danach:

```bash
terraform output   # Bucket- und Tabellennamen notieren
rm backend-setup.tf
```

`terraform/backend.tf` bleibt im Repo (leeres S3-Backend; Details kommen aus `deploy.sh`).

### 2. GitHub OIDC + IAM-Rolle

Rolle: `github-actions-twin-deploy`

**Trust Policy muss den echten `sub`-Claim erlauben.** GitHub sendet bei manchen Accounts **nicht** das Tutorial-Format:

```
repo:OWNER/REPO:*                    ← Tutorial
repo:OWNER@12345/REPO@67890:*       ← oft die Realität (mit IDs)
```

Für dieses Repo (`Marcicode93/ai-twin`) mindestens:

```json
"StringLike": {
  "token.actions.githubusercontent.com:sub": [
    "repo:Marcicode93/ai-twin:*",
    "repo:Marcicode93@*/ai-twin@*:*"
  ]
}
```

Actions in der Trust Policy:

```json
"Action": [
  "sts:AssumeRoleWithWebIdentity",
  "sts:TagSession"
]
```

Prüfen:

```bash
aws iam get-role --role-name github-actions-twin-deploy \
  --query 'Role.AssumeRolePolicyDocument' --output json
```

Bei Fehlern den echten Claim aus CloudTrail lesen:

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity \
  --max-results 3
```

### 3. GitHub Secrets

**Repository → Settings → Secrets and variables → Actions**

| Secret | Beispiel |
|--------|----------|
| `AWS_ROLE_ARN` | `arn:aws:iam::722678256685:role/github-actions-twin-deploy` |
| `AWS_ACCOUNT_ID` | `722678256685` |
| `DEFAULT_AWS_REGION` | `eu-central-1` |

**Wichtig:** Der Workflow nutzt `environment: dev`. Secrets müssen als **Repository secrets** existieren oder im Environment **`dev`** gesetzt sein. Environment-Secrets überschreiben Repo-Secrets.

### 4. GitHub Environment anlegen

**Settings → Environments → New environment → `dev`**

Optional auch `test` und `prod` für manuelle Deploys.

---

## Lokales Deploy

```bash
# Voraussetzungen: Docker (für Lambda-Build), Node, uv, Terraform, AWS CLI

export DEFAULT_AWS_REGION=eu-central-1   # oder in .env

./scripts/deploy.sh dev
# oder: prod / test
```

Was das Script macht:

1. `backend/deploy.py` → Lambda-Zip (Python **3.14**, muss zu `terraform/main.tf` passen)
2. `terraform init` mit S3-Backend
3. Workspace `dev` / `test` / `prod`
4. `terraform apply`
5. Frontend-Build → S3-Sync

Nach dem Deploy URLs anzeigen:

```bash
cd terraform && terraform workspace select dev
terraform output cloudfront_url
terraform output api_gateway_url
```

---

## GitHub Actions Deploy

**Trigger:** Push auf `main` oder manuell unter Actions → „Deploy Digital Twin“.

Workflow braucht:

```yaml
permissions:
  id-token: write   # Pflicht für OIDC
  contents: read
```

**Node-20-Warnung** in den Logs ist harmlos — kein Deploy-Blocker.

Nach erfolgreichem Run im Log prüfen:

- CloudFront URL
- API Gateway URL
- Kein Fehler bei `Configure AWS credentials`

---

## Nach dem Deploy testen

1. **CloudFront-URL** im Browser öffnen
2. Chat-Nachricht senden
3. Bei Fehlern:
   - Browser-Konsole → CORS / 404 / 500
   - Lambda-Logs: CloudWatch → `/aws/lambda/twin-dev-api` (Name je nach Environment)
   - API direkt testen:

```bash
curl -X POST "$(terraform -chdir=terraform output -raw api_gateway_url)/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"Hallo"}'
```

---

## Häufige Fehler

| Symptom | Ursache | Fix |
|---------|---------|-----|
| `AssumeRoleWithWebIdentity` | Trust Policy passt nicht zum `sub`-Claim | CloudTrail prüfen, Policy mit `@*/`-Pattern erweitern |
| `AssumeRoleWithWebIdentity` | Secret leer oder falsche Rolle | `AWS_ROLE_ARN` in Repo/Environment `dev` prüfen |
| Terraform apply: 0 added (Backend) | `backend-setup.tf` in `.terraform/` | Datei nach `terraform/backend-setup.tf` verschieben |
| Git push rejected (>100 MB) | `.terraform/`, `lambda-package/` committed | Root-`.gitignore` nutzen, History bereinigen |
| `pydantic_core` Import Error | Lambda-Runtime ≠ Build-Python | Beides auf `python3.14` (Terraform + `deploy.py`) |
| Chat 405 | Frontend ruft falsche URL | `NEXT_PUBLIC_API_URL` muss auf `.../chat` zeigen |
| Chat CORS 400 | `CORS_ORIGINS` ist ARN statt URL | CloudFront-URL (`https://d....cloudfront.net`) |
| Bedrock 403 | IAM fehlt | `AmazonBedrockFullAccess` an Lambda-Rolle |
| Bedrock 400 | Falsches Model | `global.amazon.nova-2-lite-v1:0` in `terraform.tfvars` |
| S3 AccessDenied | Falscher Bucket-Name | Exakter Name aus `terraform output`, keine Leerzeichen |

---

## Destroy

Lokal:

```bash
./scripts/destroy.sh dev
```

GitHub: Actions → „Destroy Environment“ → Environment wählen → Name zur Bestätigung eintippen.

---

## Git — was ins Repo gehört

**Ja:** Source Code, `terraform/*.tf`, `scripts/`, `.github/workflows/`, `data/`, `.env.example`

**Nein:** `.terraform/`, `lambda-package/`, `lambda-deployment.zip`, `.env`, `memory/`, `node_modules/`, `.next/`

Commit-Reihenfolge: `git add` → `git commit` → `git push`

---

## Wichtige Dateien

| Datei | Rolle |
|-------|--------|
| `scripts/deploy.sh` | Orchestriert Build + Terraform + Frontend |
| `scripts/destroy.sh` | Leert S3, `terraform destroy` |
| `terraform/backend.tf` | S3-Backend (Config via Script) |
| `terraform/main.tf` | Infrastruktur (Lambda, API GW, CloudFront, …) |
| `backend/deploy.py` | Lambda-Zip via Docker |
| `.github/workflows/deploy.yml` | CI/CD Deploy |
| `.github/workflows/destroy.yml` | CI/CD Destroy |

---

## Prod-spezifisch

In `terraform/prod.tfvars` noch prüfen:

```
bedrock_model_id = "global.amazon.nova-2-lite-v1:0"
```

(nicht `amazon.nova-lite-v1:0` ohne `global.`-Prefix)

---

## Debug OIDC (falls es wieder bricht)

Im Workflow temporär (oder einmalig lokal simulieren):

```yaml
- uses: actions/github-script@v7
  with:
    script: |
      const token = await core.getIDToken('sts.amazonaws.com')
      const payload = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString())
      console.log('sub =', payload.sub)
```

Den ausgegebenen `sub`-Wert 1:1 in der IAM Trust Policy als `StringLike`-Pattern abbilden.
