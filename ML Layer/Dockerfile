# Use AWS Lambda Python base image
# Keep runtime at 3.11 to match pinned dependency versions in requirements.txt.
FROM public.ecr.aws/lambda/python:3.11

# Copy requirements
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy Lambda function code
COPY lambda_ml_detector.py ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler
CMD ["lambda_ml_detector.lambda_handler"]