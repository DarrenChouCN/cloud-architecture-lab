## Deploy AWS Infra

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

# Deploy SNS
export TOPIC_ARN=$(aws cloudformation describe-stacks \
  --stack-name multi-cloud-faas-dev-aws \
  --region us-east-1 \
  --query "Stacks[0].Outputs[?OutputKey=='TagNotificationTopicArn'].OutputValue | [0]" \
  --output text)

echo "$TOPIC_ARN"

aws sns subscribe \
  --topic-arn "$TOPIC_ARN" \
  --protocol email \
  --notification-endpoint "your-email@example.com" \
  --attributes '{"FilterPolicy":"{\"tags\":[\"koala\",\"dingo\",\"wombat\"]}"}' \
  --return-subscription-arn \
  --region us-east-1
```

## Deploy Azure Infra
```bash
cd multi-cloud-faas-platform

az group create \
  --name rg-multicloud-faas-dev \
  --location eastus2

az bicep build --file azure/infra/main.bicep

az deployment group create \
  --resource-group rg-multicloud-faas-dev \
  --template-file azure/infra/main.bicep \
  --parameters azure/infra/parameters/dev.bicepparam \
  --mode Incremental
```


```bash
chmod +x azure/infra/scripts/upload-models.sh
./azure/infra/scripts/upload-models.sh
```