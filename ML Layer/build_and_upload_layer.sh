#!/bin/bash
# Build ML Layer and Upload to S3 (for layers > 50MB)

PYTHON_VERSION="3.11"  # Change to 3.11 if you prefer
BUCKET="datasourcebucket1109"
LAYER_NAME="ml-sklearn-layer"

echo "🚀 Building Lambda Layer for Python ${PYTHON_VERSION}..."

# Clean up
rm -rf python
rm -f ${LAYER_NAME}.zip

# Create directory
mkdir -p python

echo "📦 Installing scikit-learn and numpy..."

# Install for specific Python version
pip install \
    --platform manylinux2014_x86_64 \
    --target=python \
    --python-version ${PYTHON_VERSION} \
    --only-binary=:all: \
    scikit-learn==1.3.0 \
    numpy==1.24.3

echo "🗑️  Cleaning up to reduce size..."

# Remove unnecessary files
find python -type d -name "tests" -exec rm -rf {} + 2>/dev/null
find python -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find python -name "*.pyc" -delete
find python -name "*.pyo" -delete
find python -name "*.dist-info" -exec rm -rf {}/LICENSE {} + 2>/dev/null
find python -name "*.dist-info" -exec rm -rf {}/COPYING* {} + 2>/dev/null

# Remove .so debug symbols
find python -name "*.so" -exec strip {} \; 2>/dev/null

# Remove large test files
rm -rf python/numpy/tests 2>/dev/null
rm -rf python/sklearn/datasets/tests 2>/dev/null
rm -rf python/sklearn/*/tests 2>/dev/null

echo "📊 Size check..."
du -sh python

echo "🗜️  Creating zip..."
zip -r9 ${LAYER_NAME}.zip python -q

echo ""
echo "✅ Layer created!"
ls -lh ${LAYER_NAME}.zip

LAYER_SIZE=$(stat -f%z ${LAYER_NAME}.zip 2>/dev/null || stat -c%s ${LAYER_NAME}.zip)
LAYER_SIZE_MB=$((LAYER_SIZE / 1024 / 1024))

echo ""
echo "📏 Layer size: ${LAYER_SIZE_MB} MB"

if [ ${LAYER_SIZE_MB} -lt 50 ]; then
    echo "✅ Size < 50MB - can upload directly in AWS Console!"
    echo ""
    echo "Upload instructions:"
    echo "  1. Go to AWS Lambda Console → Layers"
    echo "  2. Create layer"
    echo "  3. Upload ${LAYER_NAME}.zip directly"
else
    echo "📤 Size > 50MB - uploading to S3 first..."
    
    # Upload to S3
    aws s3 cp ${LAYER_NAME}.zip s3://${BUCKET}/layers/${LAYER_NAME}.zip
    
    echo ""
    echo "✅ Uploaded to S3!"
    echo ""
    echo "📋 To create Lambda Layer from S3:"
    echo ""
    echo "Option A - AWS CLI:"
    echo "  aws lambda publish-layer-version \\"
    echo "    --layer-name ${LAYER_NAME} \\"
    echo "    --content S3Bucket=${BUCKET},S3Key=layers/${LAYER_NAME}.zip \\"
    echo "    --compatible-runtimes python${PYTHON_VERSION}"
    echo ""
    echo "Option B - AWS Console:"
    echo "  1. Go to Lambda → Layers → Create layer"
    echo "  2. Name: ${LAYER_NAME}"
    echo "  3. Choose 'Upload from S3'"
    echo "  4. S3 URI: s3://${BUCKET}/layers/${LAYER_NAME}.zip"
    echo "  5. Compatible runtime: Python ${PYTHON_VERSION}"
fi

echo ""
echo "🎯 Next steps:"
echo "  1. Create this layer in Lambda"
echo "  2. Add AWS Data Wrangler layer: arn:aws:lambda:us-east-1:336392948345:layer:AWSSDKPandas-Python${PYTHON_VERSION/./}:13"
echo "  3. Attach both layers to your ML Lambda function"