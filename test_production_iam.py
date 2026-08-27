#!/usr/bin/env python3
"""Test script to verify production console-chat-responder IAM permissions."""

import os
import sys
import json
from datetime import datetime, timedelta

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("❌ ERROR: boto3 not installed")
    print("Run: poetry install")
    sys.exit(1)


def main():
    print("=" * 50)
    print("Production Console Chat IAM Fix Test")
    print("=" * 50)
    print()

    # Setup AWS session
    os.environ.setdefault("AWS_PROFILE", "Ryan")
    os.environ.setdefault("AWS_REGION", "us-east-1")
    
    session = boto3.Session(
        profile_name=os.environ.get("AWS_PROFILE"),
        region_name=os.environ.get("AWS_REGION")
    )
    
    lambda_client = session.client("lambda")
    iam_client = session.client("iam")
    logs_client = session.client("logs")
    
    function_name = "amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D"
    
    print("1. Checking Lambda function configuration...")
    print("-" * 50)
    
    try:
        response = lambda_client.get_function(FunctionName=function_name)
        print("✓ Lambda function exists")
        print()
        
        config = response["Configuration"]
        role_arn = config["Role"]
        role_name = role_arn.split("/")[-1]
        
        print(f"Function ARN: {config['FunctionArn']}")
        print(f"Role ARN: {role_arn}")
        print(f"Role Name: {role_name}")
        print(f"Last Modified: {config['LastModified']}")
        print()
        
    except ClientError as e:
        print(f"❌ ERROR: {e}")
        return 1
    
    print("2. Checking IAM role policies for SSM permissions...")
    print("-" * 50)
    
    try:
        # Get inline policies
        inline_response = iam_client.list_role_policies(RoleName=role_name)
        inline_policies = inline_response.get("PolicyNames", [])
        
        if not inline_policies:
            print("⚠️  No inline policies found")
            return 1
        
        print(f"Found {len(inline_policies)} inline policies")
        print()
        
        has_get_parameters = False
        has_ssm_resources = False
        
        for policy_name in inline_policies:
            policy_response = iam_client.get_role_policy(
                RoleName=role_name,
                PolicyName=policy_name
            )
            
            policy_doc = json.dumps(policy_response["PolicyDocument"])
            
            # Check for SSM actions
            if "ssm:GetParameters" in policy_doc:
                print(f"✓ Found ssm:GetParameters in policy: {policy_name}")
                has_get_parameters = True
            
            if "ssm:GetParameter" in policy_doc:
                print(f"✓ Found ssm:GetParameter in policy: {policy_name}")
            
            # Check for proper resource ARNs
            if "parameter/amplify/papyrus/" in policy_doc:
                print(f"✓ Found Amplify Papyrus SSM path in policy: {policy_name}")
                has_ssm_resources = True
            
            if "parameter/amplify/dbsyytcm9drqa/" in policy_doc:
                print(f"✓ Found production app SSM path in policy: {policy_name}")
                has_ssm_resources = True
        
        print()
        
        if has_get_parameters and has_ssm_resources:
            print("✅ SUCCESS: IAM permissions are correctly configured!")
            print()
            print("The Lambda has:")
            print("  - ssm:GetParameters action")
            print("  - Proper Amplify SSM resource paths")
            print()
        else:
            print("❌ PROBLEM: Missing required IAM permissions")
            if not has_get_parameters:
                print("  - Missing ssm:GetParameters action")
            if not has_ssm_resources:
                print("  - Missing proper SSM resource paths")
            print()
            return 1
            
    except ClientError as e:
        print(f"❌ ERROR checking IAM policies: {e}")
        return 1
    
    print("3. Checking Lambda environment variables...")
    print("-" * 50)
    
    env_vars = config.get("Environment", {}).get("Variables", {})
    
    if "PAPYRUS_GRAPHQL_ENDPOINT" in env_vars:
        print(f"✓ PAPYRUS_GRAPHQL_ENDPOINT: {env_vars['PAPYRUS_GRAPHQL_ENDPOINT']}")
    else:
        print("⚠️  PAPYRUS_GRAPHQL_ENDPOINT not set")
    
    if "AMPLIFY_SSM_ENV_CONFIG" in env_vars:
        print(f"✓ AMPLIFY_SSM_ENV_CONFIG: {env_vars['AMPLIFY_SSM_ENV_CONFIG']}")
    else:
        print("⚠️  AMPLIFY_SSM_ENV_CONFIG not set")
    
    if "PAPYRUS_MESSAGE_TABLE_NAME" in env_vars:
        print(f"✓ PAPYRUS_MESSAGE_TABLE_NAME: {env_vars['PAPYRUS_MESSAGE_TABLE_NAME']}")
    
    print()
    
    print("4. Checking recent Lambda invocations...")
    print("-" * 50)
    
    log_group = f"/aws/lambda/{function_name}"
    
    try:
        # Get recent log streams
        streams_response = logs_client.describe_log_streams(
            logGroupName=log_group,
            orderBy="LastEventTime",
            descending=True,
            limit=3
        )
        
        streams = streams_response.get("logStreams", [])
        
        if streams:
            print(f"✓ Found {len(streams)} recent log streams")
            print()
            
            # Get recent events from the most recent stream
            latest_stream = streams[0]["logStreamName"]
            print(f"Latest stream: {latest_stream}")
            print()
            
            # Get events from last 5 minutes
            start_time = int((datetime.now() - timedelta(minutes=5)).timestamp() * 1000)
            
            events_response = logs_client.get_log_events(
                logGroupName=log_group,
                logStreamName=latest_stream,
                startTime=start_time,
                limit=50
            )
            
            events = events_response.get("events", [])
            
            if events:
                print(f"Recent log events ({len(events)} found):")
                print("-" * 50)
                
                # Look for errors or JWT-related messages
                has_jwt_error = False
                has_success = False
                
                for event in events[-20:]:  # Show last 20
                    message = event["message"].strip()
                    if message:
                        # Highlight important messages
                        if "JWT" in message or "jwt" in message:
                            print(f"🔍 {message}")
                            if "error" in message.lower() or "fail" in message.lower():
                                has_jwt_error = True
                            else:
                                has_success = True
                        elif "error" in message.lower() or "ERROR" in message:
                            print(f"❌ {message}")
                        elif "COMPLETED" in message or "success" in message.lower():
                            print(f"✓ {message}")
                            has_success = True
                        else:
                            print(f"   {message}")
                
                print()
                
                if has_jwt_error:
                    print("⚠️  Found JWT-related errors in recent logs")
                    print("The IAM fix may not be working correctly")
                    return 1
                elif has_success:
                    print("✓ No JWT errors found in recent logs")
            else:
                print("No recent events in the last 5 minutes")
        else:
            print("No recent log streams found")
            print("The Lambda may not have been invoked recently")
        
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"⚠️  Log group not found: {log_group}")
        else:
            print(f"❌ ERROR checking logs: {e}")
    
    print()
    print("=" * 50)
    print("Test Complete - IAM Fix Verified")
    print("=" * 50)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
