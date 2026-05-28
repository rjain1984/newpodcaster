"""Centralized configuration. Reads env vars and Secrets Manager once per cold start."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import boto3


@dataclass(frozen=True)
class Config:
    s3_bucket: str
    gemini_api_key: str
    aws_region: str


def load_config() -> Config:
    s3_bucket = os.environ["S3_BUCKET"]
    secret_name = os.environ["GEMINI_SECRET_NAME"]
    region = os.environ.get("AWS_REGION", "us-west-2")

    sm = boto3.client("secretsmanager", region_name=region)
    secret_raw = sm.get_secret_value(SecretId=secret_name)["SecretString"]
    gemini_api_key = json.loads(secret_raw)["api_key"]

    return Config(s3_bucket=s3_bucket, gemini_api_key=gemini_api_key, aws_region=region)
