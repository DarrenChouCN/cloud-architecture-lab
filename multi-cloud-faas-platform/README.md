## Deploy Infra

```bash
cd multi-cloud-faas-platform

sam validate --template-file aws/template.yaml

sam build --template-file aws/template.yaml

sam deploy \
  --template-file aws/template.yaml \
  --stack-name multi-cloud-faas-dev-aws \
  --region us-east-1 \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides \
    ProjectName=multi-cloud-faas \
    Environment=dev \
    AuthDomainPrefix=shaomin-faas-dev
```

```bash
python3 -m http.server 3000
```