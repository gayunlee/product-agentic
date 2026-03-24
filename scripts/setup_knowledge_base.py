"""
Bedrock Knowledge Base 셋업 스크립트.

1. S3 버킷 생성 (없으면)
2. knowledge/*.md + scenarios/multi-agent/*.md 업로드
3. Knowledge Base 생성
4. Data Source 연결 + 동기화

Usage:
    uv run python scripts/setup_knowledge_base.py

환경변수:
    AWS_REGION (default: us-west-2)
    KB_BUCKET_NAME (default: us-product-agent-knowledge)
"""

import os
import sys
import json
import time
import boto3
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

REGION = os.environ.get("AWS_REGION", "us-west-2")
BUCKET_NAME = os.environ.get("KB_BUCKET_NAME", "us-product-agent-knowledge")
KB_NAME = "us-product-agent-domain-knowledge"
KB_DESCRIPTION = "관리자센터 상품 세팅 도메인 지식 — 마스터, 오피셜클럽, 상품 페이지, 진단 시나리오 등"
EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
PROJECT_ROOT = Path(__file__).parent.parent


def get_account_id():
    sts = boto3.client("sts", region_name=REGION)
    return sts.get_caller_identity()["Account"]


# ── Step 1: S3 버킷 ──

def ensure_bucket(s3):
    """S3 버킷이 없으면 생성."""
    try:
        s3.head_bucket(Bucket=BUCKET_NAME)
        print(f"✅ S3 버킷 존재: {BUCKET_NAME}")
    except s3.exceptions.ClientError:
        print(f"📦 S3 버킷 생성: {BUCKET_NAME}")
        if REGION == "us-east-1":
            s3.create_bucket(Bucket=BUCKET_NAME)
        else:
            s3.create_bucket(
                Bucket=BUCKET_NAME,
                CreateBucketConfiguration={"LocationConstraint": REGION},
            )
        print(f"✅ S3 버킷 생성 완료")


def upload_files(s3):
    """knowledge/*.md + scenarios/multi-agent/*.md를 S3에 업로드."""
    uploaded = 0

    # knowledge 폴더
    knowledge_dir = PROJECT_ROOT / "knowledge"
    for f in knowledge_dir.glob("*.md"):
        key = f"knowledge/{f.name}"
        s3.upload_file(str(f), BUCKET_NAME, key)
        print(f"  📄 {key}")
        uploaded += 1

    # scenarios/multi-agent 폴더
    scenarios_dir = PROJECT_ROOT / "scenarios" / "multi-agent"
    for f in scenarios_dir.glob("*.md"):
        key = f"scenarios/{f.name}"
        s3.upload_file(str(f), BUCKET_NAME, key)
        print(f"  📄 {key}")
        uploaded += 1

    print(f"✅ {uploaded}개 파일 업로드 완료")
    return uploaded


# ── Step 2: IAM Role ──

def ensure_kb_role(iam, account_id):
    """KB용 IAM Role이 없으면 생성."""
    role_name = "BedrockKnowledgeBaseRole-ProductAgent"

    try:
        role = iam.get_role(RoleName=role_name)
        print(f"✅ IAM Role 존재: {role_name}")
        return role["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        pass

    print(f"🔐 IAM Role 생성: {role_name}")

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": account_id},
                "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock:{REGION}:{account_id}:knowledge-base/*"},
            },
        }],
    }

    role = iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description="Bedrock KB role for us-product-agent",
    )

    # S3 + Bedrock 권한 추가
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:ListBucket"],
                "Resource": [
                    f"arn:aws:s3:::{BUCKET_NAME}",
                    f"arn:aws:s3:::{BUCKET_NAME}/*",
                ],
            },
            {
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel"],
                "Resource": [f"arn:aws:bedrock:{REGION}::foundation-model/{EMBEDDING_MODEL}"],
            },
        ],
    }

    iam.put_role_policy(
        RoleName=role_name,
        PolicyName="BedrockKBAccess",
        PolicyDocument=json.dumps(policy),
    )

    # Role 전파 대기
    print("  ⏳ IAM Role 전파 대기 (10초)...")
    time.sleep(10)

    print(f"✅ IAM Role 생성 완료: {role['Role']['Arn']}")
    return role["Role"]["Arn"]


# ── Step 3: Knowledge Base ──

def find_existing_kb(bedrock_agent):
    """이미 존재하는 KB가 있는지 확인."""
    response = bedrock_agent.list_knowledge_bases(maxResults=100)
    for kb in response.get("knowledgeBaseSummaries", []):
        if kb["name"] == KB_NAME:
            return kb["knowledgeBaseId"]
    return None


def create_knowledge_base(bedrock_agent, role_arn):
    """Knowledge Base 생성."""
    existing_id = find_existing_kb(bedrock_agent)
    if existing_id:
        print(f"✅ Knowledge Base 이미 존재: {existing_id}")
        return existing_id

    print(f"🧠 Knowledge Base 생성: {KB_NAME}")

    response = bedrock_agent.create_knowledge_base(
        name=KB_NAME,
        description=KB_DESCRIPTION,
        roleArn=role_arn,
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": f"arn:aws:bedrock:{REGION}::foundation-model/{EMBEDDING_MODEL}",
            },
        },
        storageConfiguration={
            "type": "BEDROCK_DEFAULT",
        },
    )

    kb_id = response["knowledgeBase"]["knowledgeBaseId"]
    print(f"✅ Knowledge Base 생성 완료: {kb_id}")

    # ACTIVE 대기
    print("  ⏳ KB 활성화 대기...")
    for _ in range(30):
        kb = bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
        status = kb["knowledgeBase"]["status"]
        if status == "ACTIVE":
            print(f"  ✅ KB 활성화 완료")
            break
        time.sleep(5)
    else:
        print(f"  ⚠️ KB 상태: {status} (시간 초과)")

    return kb_id


# ── Step 4: Data Source ──

def find_existing_ds(bedrock_agent, kb_id):
    """이미 존재하는 Data Source가 있는지 확인."""
    response = bedrock_agent.list_data_sources(knowledgeBaseId=kb_id, maxResults=10)
    for ds in response.get("dataSourceSummaries", []):
        if ds["name"] == f"{KB_NAME}-s3":
            return ds["dataSourceId"]
    return None


def create_data_source(bedrock_agent, kb_id):
    """S3 Data Source 연결."""
    existing_id = find_existing_ds(bedrock_agent, kb_id)
    if existing_id:
        print(f"✅ Data Source 이미 존재: {existing_id}")
        return existing_id

    print(f"📂 Data Source 생성: S3 → KB")

    response = bedrock_agent.create_data_source(
        knowledgeBaseId=kb_id,
        name=f"{KB_NAME}-s3",
        description="knowledge/*.md + scenarios/multi-agent/*.md",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": f"arn:aws:s3:::{BUCKET_NAME}",
            },
        },
    )

    ds_id = response["dataSource"]["dataSourceId"]
    print(f"✅ Data Source 생성 완료: {ds_id}")
    return ds_id


def sync_data_source(bedrock_agent, kb_id, ds_id):
    """Data Source 동기화 (임베딩 생성)."""
    print(f"🔄 동기화 시작...")

    bedrock_agent.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=ds_id,
    )

    # 동기화 완료 대기
    for i in range(60):
        jobs = bedrock_agent.list_ingestion_jobs(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id,
            maxResults=1,
            sortBy={"attribute": "STARTED_AT", "order": "DESCENDING"},
        )
        if jobs["ingestionJobSummaries"]:
            status = jobs["ingestionJobSummaries"][0]["status"]
            if status == "COMPLETE":
                stats = jobs["ingestionJobSummaries"][0].get("statistics", {})
                print(f"  ✅ 동기화 완료: {stats.get('numberOfDocumentsScanned', '?')}개 문서 처리")
                return
            elif status == "FAILED":
                print(f"  ❌ 동기화 실패")
                return
            print(f"  ⏳ 동기화 중... ({status})", end="\r")
        time.sleep(5)

    print(f"  ⚠️ 동기화 시간 초과")


# ── Main ──

def main():
    print("=" * 50)
    print("Bedrock Knowledge Base 셋업")
    print("=" * 50)

    account_id = get_account_id()
    print(f"AWS Account: {account_id}")
    print(f"Region: {REGION}")
    print()

    s3 = boto3.client("s3", region_name=REGION)
    iam = boto3.client("iam", region_name=REGION)
    bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)

    # Step 1: S3
    print("[1/4] S3 버킷")
    ensure_bucket(s3)
    upload_files(s3)
    print()

    # Step 2: IAM
    print("[2/4] IAM Role")
    role_arn = ensure_kb_role(iam, account_id)
    print()

    # Step 3: KB
    print("[3/4] Knowledge Base")
    kb_id = create_knowledge_base(bedrock_agent, role_arn)
    print()

    # Step 4: Data Source + Sync
    print("[4/4] Data Source + 동기화")
    ds_id = create_data_source(bedrock_agent, kb_id)
    sync_data_source(bedrock_agent, kb_id, ds_id)
    print()

    # 결과 출력
    print("=" * 50)
    print("✅ 셋업 완료!")
    print(f"  Knowledge Base ID: {kb_id}")
    print(f"  S3 Bucket: {BUCKET_NAME}")
    print(f"  Region: {REGION}")
    print()
    print("도메인 에이전트에 추가할 환경변수:")
    print(f"  KNOWLEDGE_BASE_ID={kb_id}")
    print("=" * 50)

    # .env에 KB_ID 추가
    env_path = PROJECT_ROOT / ".env"
    env_content = env_path.read_text() if env_path.exists() else ""
    if "KNOWLEDGE_BASE_ID" not in env_content:
        with open(env_path, "a") as f:
            f.write(f"\n# Bedrock Knowledge Base\nKNOWLEDGE_BASE_ID={kb_id}\n")
        print(f"  → .env에 KNOWLEDGE_BASE_ID 추가됨")


if __name__ == "__main__":
    main()
