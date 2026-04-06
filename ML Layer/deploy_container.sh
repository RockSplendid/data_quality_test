#!/bin/bash
# Deploy ML Lambda using Container Image (bypasses layer size limits)

set -e

# Configuration
AWS_REGION="eu-north-1"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO_NAME="ml-anomaly-detector"
IMAGE_TAG="latest"
LAMBDA_FUNCTION_NAME="lambda-ml-detector"

echo "Deploying ML Lambda as Container Image"
echo "=========================================="
echo "Region: ${AWS_REGION}"
echo "Account: ${AWS_ACCOUNT_ID}"
echo "ECR Repo: ${ECR_REPO_NAME}"
echo ""

# Step 1: Create ECR repository (if doesn't exist)
echo "Step 1: Creating ECR repository..."
aws ecr describe-repositories --repository-names ${ECR_REPO_NAME} --region ${AWS_REGION} 2>/dev/null || \
aws ecr create-repository \
    --repository-name ${ECR_REPO_NAME} \
    --region ${AWS_REGION} \
    --image-scanning-configuration scanOnPush=true

ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"
echo "✓ ECR repository: ${ECR_URI}"

# Step 2: Login to ECR
echo ""
echo "Step 2: Logging in to ECR..."
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_URI}
echo "✓ Logged in to ECR"

# Step 3: Build Docker image
echo ""
echo "Step 3: Building Docker image..."
docker build --platform linux/amd64 -t ${ECR_REPO_NAME}:${IMAGE_TAG} .
echo "✓ Docker image built"

# Step 4: Tag image
echo ""
echo "Step 4: Tagging image..."
docker tag ${ECR_REPO_NAME}:${IMAGE_TAG} ${ECR_URI}:${IMAGE_TAG}
echo "✓ Image tagged"

# Step 5: Push to ECR
echo ""
echo "Step 5: Pushing to ECR..."
docker push ${ECR_URI}:${IMAGE_TAG}
echo "✓ Image pushed to ECR"

# Step 6: Create/Update Lambda function
echo ""
echo "Step 6: Creating/Updating Lambda function..."

# Check if function exists
if aws lambda get-function --function-name ${LAMBDA_FUNCTION_NAME} --region ${AWS_REGION} 2>/dev/null; then
    echo "Updating existing function..."
    aws lambda update-function-code \
        --function-name ${LAMBDA_FUNCTION_NAME} \
        --image-uri ${ECR_URI}:${IMAGE_TAG} \
        --region ${AWS_REGION}
    
    # Wait for update to complete
    aws lambda wait function-updated \
        --function-name ${LAMBDA_FUNCTION_NAME} \
        --region ${AWS_REGION}
    
    echo "✓ Lambda function updated"
else
    echo "Creating new function..."
    
    # Get or create execution role
    ROLE_NAME="${LAMBDA_FUNCTION_NAME}-role"
    
    # Check if role exists
    if ! aws iam get-role --role-name ${ROLE_NAME} 2>/dev/null; then
        echo "Creating IAM role..."
        
        # Create trust policy
        cat > /tmp/trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
        
        aws iam create-role \
            --role-name ${ROLE_NAME} \
            --assume-role-policy-document file:///tmp/trust-policy.json
        
        # Attach policies
        aws iam attach-role-policy \
            --role-name ${ROLE_NAME} \
            --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
        
        # Create S3 policy
        cat > /tmp/s3-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::datasourcebucket1109/*",
        "arn:aws:s3:::datasourcebucket1109"
      ]
    }
  ]
}
EOF
        
        aws iam put-role-policy \
            --role-name ${ROLE_NAME} \
            --policy-name S3Access \
            --policy-document file:///tmp/s3-policy.json
        
        echo "✓ IAM role created"
        echo "Waiting 10 seconds for role to propagate..."
        sleep 10
    fi
    
    ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${ROLE_NAME}"
    
    # Create function
    aws lambda create-function \
        --function-name ${LAMBDA_FUNCTION_NAME} \
        --package-type Image \
        --code ImageUri=${ECR_URI}:${IMAGE_TAG} \
        --role ${ROLE_ARN} \
        --timeout 300 \
        --memory-size 2048 \
        --environment Variables="{BUCKET_NAME=datasourcebucket1109,LOG_LEVEL=INFO}" \
        --region ${AWS_REGION}
    
    echo "✓ Lambda function created"
fi

# Step 7: Configure S3 trigger
echo ""
echo "Step 7: Configuring S3 trigger..."

# Add Lambda permission for S3
aws lambda add-permission \
    --function-name ${LAMBDA_FUNCTION_NAME} \
    --statement-id s3-trigger-permission \
    --action lambda:InvokeFunction \
    --principal s3.amazonaws.com \
    --source-arn arn:aws:s3:::datasourcebucket1109 \
    --region ${AWS_REGION} 2>/dev/null || echo "Permission already exists"

# Get Lambda ARN
LAMBDA_ARN=$(aws lambda get-function --function-name ${LAMBDA_FUNCTION_NAME} --region ${AWS_REGION} --query 'Configuration.FunctionArn' --output text)

echo ""
echo "MANUAL STEP REQUIRED:"
echo "Configure S3 trigger in AWS Console:"
echo "  1. Go to S3 bucket: datasourcebucket1109"
echo "  2. Properties → Event notifications → Create event notification"
echo "  3. Event name: ml-lambda-trigger"
echo "  4. Prefix: CleanZone-RulesBased/"
echo "  5. Suffix: .parquet"
echo "  6. Event type: PUT"
echo "  7. Destination: Lambda function"
echo "  8. Lambda function: ${LAMBDA_FUNCTION_NAME}"
echo ""
echo "Or use this AWS CLI command:"
echo ""
cat <<EOF
aws s3api put-bucket-notification-configuration \\
  --bucket datasourcebucket1109 \\
  --notification-configuration '{
    "LambdaFunctionConfigurations": [
      {
        "Id": "ml-lambda-trigger",
        "LambdaFunctionArn": "${LAMBDA_ARN}",
        "Events": ["s3:ObjectCreated:Put"],
        "Filter": {
          "Key": {
            "FilterRules": [
              {"Name": "prefix", "Value": "CleanZone-RulesBased/"},
              {"Name": "suffix", "Value": ".parquet"}
            ]
          }
        }
      }
    ]
  }'
EOF

echo ""
echo "=========================================="
echo "DEPLOYMENT COMPLETE!"
echo "=========================================="
echo ""
echo "Summary:"
echo "  Function: ${LAMBDA_FUNCTION_NAME}"
echo "  Image: ${ECR_URI}:${IMAGE_TAG}"
echo "  Memory: 2048 MB"
echo "  Timeout: 300 seconds"
echo ""
echo "Test the function:"
echo "  aws lambda invoke --function-name ${LAMBDA_FUNCTION_NAME} --payload '{}' response.json"
echo ""
echo "View logs:"
echo "  aws logs tail /aws/lambda/${LAMBDA_FUNCTION_NAME} --follow"