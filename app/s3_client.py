# app/s3_client.py
import os
import boto3
from botocore.client import Config

s3 = boto3.client(
    "s3",
    endpoint_url=f"http://{os.getenv('MINIO_ENDPOINT')}",
    aws_access_key_id=os.getenv("MINIO_ROOT_USER"),
    aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD"),
    config=Config(signature_version="s3v4"),
    region_name="us-east-1"  
)

BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME")

def upload_file_to_s3(file_path: str, object_name: str):
    """Upload file to s3 bucket."""
    s3.upload_file(file_path, BUCKET_NAME, object_name)
    public_url = f"http://{os.getenv('PUBLIC_HOST')}:9010/{BUCKET_NAME}/{object_name}"
    return public_url