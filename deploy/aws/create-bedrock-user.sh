#!/bin/bash
# One-time setup: an IAM user that can ONLY call Bedrock, for the Dock server in Kubernetes.
# Its keys go into the local AWS profile "echodock-bedrock" (they are never printed),
# and `make secret AWS=echodock-bedrock` copies them into the cluster.
#
# Run it signed in with an account that can manage IAM:  bash deploy/aws/create-bedrock-user.sh
# Undo:  aws iam delete-access-key ... ; aws iam delete-user-policy ... ; aws iam delete-user ...
#
# The policy was generated from server/dock_server/bedrock.py by IAM Policy Autopilot.

set -euo pipefail
USER_NAME=echodock-bedrock
PROFILE=echodock-bedrock
REGION=us-east-1

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["bedrock:ApplyGuardrail", "bedrock:InvokeTool"],
      "Resource": [
        "arn:aws:bedrock::$ACCOUNT:system-tool/*",
        "arn:aws:bedrock:$REGION:$ACCOUNT:guardrail-profile/*",
        "arn:aws:bedrock:$REGION:$ACCOUNT:guardrail/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:CallWithBearerToken", "bedrock:InvokeModel"],
      "Resource": "*"
    }
  ]
}
EOF
)

if aws iam get-user --user-name "$USER_NAME" >/dev/null 2>&1; then
  echo "IAM user $USER_NAME already exists."
else
  aws iam create-user --user-name "$USER_NAME" --tags Key=project,Value=echodock >/dev/null
  echo "Created IAM user $USER_NAME."
fi
aws iam put-user-policy --user-name "$USER_NAME" --policy-name echodock-bedrock-invoke --policy-document "$POLICY"
echo "Gave it Bedrock-only permissions."

if aws configure get aws_access_key_id --profile "$PROFILE" >/dev/null 2>&1; then
  echo "Profile $PROFILE already has keys; not making new ones."
else
  read -r KEY_ID KEY_SECRET <<< "$(aws iam create-access-key --user-name "$USER_NAME" \
    --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)"
  aws configure set aws_access_key_id "$KEY_ID" --profile "$PROFILE"
  aws configure set aws_secret_access_key "$KEY_SECRET" --profile "$PROFILE"
  aws configure set region "$REGION" --profile "$PROFILE"
  unset KEY_SECRET
  echo "Saved new access keys in AWS profile $PROFILE (~/.aws/credentials)."
fi

echo "Next: make secret AWS=$PROFILE"
