#!/usr/bin/env python3
"""
Test script to verify production web console chat is working.
Checks IAM permissions, CloudWatch logs, and recent message status.

Usage:
    export AWS_PROFILE=Ryan AWS_REGION=us-east-1
    python3 scripts/test-console-chat-production.py
"""
import boto3
import json
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any

def check_lambda_iam_permissions() -> Dict[str, Any]:
    """Check if console-chat-responder Lambda has correct SSM permissions."""
    print("=" * 80)
    print("1. Checking Lambda IAM Permissions")
    print("=" * 80)
    
    iam = boto3.client('iam')
    lambda_client = boto3.client('lambda')
    
    # Find the console-chat-responder Lambda
    try:
        response = lambda_client.list_functions()
        responder_function = None
        for func in response['Functions']:
            if 'console-chat-responder' in func['FunctionName'].lower():
                responder_function = func
                break
        
        if not responder_function:
            print("❌ Could not find console-chat-responder Lambda function")
            return {"status": "FAIL", "reason": "Lambda not found"}
        
        function_name = responder_function['FunctionName']
        print(f"✓ Found Lambda: {function_name}")
        
        # Get the Lambda's role
        role_arn = responder_function['Role']
        role_name = role_arn.split('/')[-1]
        print(f"✓ Role: {role_name}")
        
        # Check role policies
        inline_policies = iam.list_role_policies(RoleName=role_name)
        attached_policies = iam.list_attached_role_policies(RoleName=role_name)
        
        has_get_parameter = False
        has_get_parameters = False
        
        # Check inline policies
        for policy_name in inline_policies['PolicyNames']:
            policy = iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)
            policy_doc = policy['PolicyDocument']
            
            for statement in policy_doc.get('Statement', []):
                actions = statement.get('Action', [])
                if isinstance(actions, str):
                    actions = [actions]
                
                for action in actions:
                    if action == 'ssm:GetParameter' or action == 'ssm:*':
                        has_get_parameter = True
                    if action == 'ssm:GetParameters' or action == 'ssm:*':
                        has_get_parameters = True
        
        print(f"\nSSM Permissions:")
        print(f"  ssm:GetParameter:  {'✓' if has_get_parameter else '❌'}")
        print(f"  ssm:GetParameters: {'✓' if has_get_parameters else '❌'} (REQUIRED FOR FIX)")
        
        if has_get_parameter and has_get_parameters:
            print("\n✅ IAM permissions are correct!")
            return {"status": "PASS", "function_name": function_name}
        else:
            print("\n❌ Missing required IAM permissions!")
            print("   The fix may not be deployed yet.")
            return {"status": "FAIL", "reason": "Missing ssm:GetParameters permission"}
            
    except Exception as e:
        print(f"❌ Error checking IAM: {e}")
        return {"status": "ERROR", "error": str(e)}

def check_cloudwatch_logs() -> Dict[str, Any]:
    """Check CloudWatch logs for JWT signing secret errors."""
    print("\n" + "=" * 80)
    print("2. Checking CloudWatch Logs for JWT Errors")
    print("=" * 80)
    
    logs = boto3.client('logs')
    
    try:
        # Find console-chat-responder log group
        response = logs.describe_log_groups(logGroupNamePrefix='/aws/lambda/')
        
        responder_log_group = None
        for group in response['logGroups']:
            if 'console-chat-responder' in group['logGroupName'].lower():
                responder_log_group = group['logGroupName']
                break
        
        if not responder_log_group:
            print("❌ Could not find console-chat-responder log group")
            return {"status": "FAIL", "reason": "Log group not found"}
        
        print(f"✓ Found log group: {responder_log_group}")
        
        # Query last 15 minutes for JWT errors
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=15)
        
        print(f"\nSearching logs from {start_time.isoformat()} to {end_time.isoformat()}...")
        
        start_query_response = logs.start_query(
            logGroupName=responder_log_group,
            startTime=int(start_time.timestamp()),
            endTime=int(end_time.timestamp()),
            queryString='fields @timestamp, @message | filter @message like /JWT signing secret/ or @message like /Could not resolve JWT/ | sort @timestamp desc | limit 20'
        )
        
        query_id = start_query_response['queryId']
        
        # Wait for query to complete
        import time
        response = None
        for _ in range(30):  # Wait up to 30 seconds
            time.sleep(1)
            response = logs.get_query_results(queryId=query_id)
            if response['status'] == 'Complete':
                break
        
        if not response or response['status'] != 'Complete':
            print("⚠️  Query timed out")
            return {"status": "WARNING", "reason": "Query timeout"}
        
        results = response['results']
        if results:
            print(f"\n❌ Found {len(results)} JWT signing secret errors in last 15 minutes:")
            for result in results[:5]:  # Show first 5
                timestamp = next((r['value'] for r in result if r['field'] == '@timestamp'), 'N/A')
                message = next((r['value'] for r in result if r['field'] == '@message'), 'N/A')
                print(f"\n  {timestamp}")
                print(f"  {message[:200]}...")
            
            return {"status": "FAIL", "error_count": len(results)}
        else:
            print("\n✅ No JWT signing secret errors found in last 15 minutes!")
            return {"status": "PASS"}
            
    except Exception as e:
        print(f"❌ Error checking logs: {e}")
        return {"status": "ERROR", "error": str(e)}

def check_recent_messages() -> Dict[str, Any]:
    """Check DynamoDB for recent console chat messages and their status."""
    print("\n" + "=" * 80)
    print("3. Checking Recent Console Chat Messages")
    print("=" * 80)
    
    dynamodb = boto3.client('dynamodb')
    
    try:
        # Find Message table
        tables = dynamodb.list_tables()
        message_table = None
        for table in tables['TableNames']:
            if 'Message' in table and 'papyrus' in table.lower():
                message_table = table
                break
        
        if not message_table:
            print("❌ Could not find Message table")
            return {"status": "FAIL", "reason": "Message table not found"}
        
        print(f"✓ Found Message table: {message_table}")
        
        # Query recent messages with channel=console_chat
        # Since we don't know the exact key schema, let's scan for recent items
        response = dynamodb.scan(
            TableName=message_table,
            Limit=100,
            FilterExpression='attribute_exists(#channel) AND #channel = :console_chat',
            ExpressionAttributeNames={'#channel': 'channel'},
            ExpressionAttributeValues={':console_chat': {'S': 'console_chat'}}
        )
        
        items = response.get('Items', [])
        print(f"\n✓ Found {len(items)} recent console chat messages")
        
        if not items:
            print("\n⚠️  No recent console chat messages found")
            return {"status": "WARNING", "reason": "No recent messages"}
        
        # Analyze message status
        completed = 0
        failed = 0
        running = 0
        
        recent_failures = []
        
        for item in items:
            status = item.get('turnStatus', {}).get('S', 'unknown')
            role = item.get('role', {}).get('S', 'unknown')
            created_at = item.get('createdAt', {}).get('S', 'unknown')
            
            if status == 'COMPLETED':
                completed += 1
            elif status == 'FAILED':
                failed += 1
                if role == 'ASSISTANT':
                    error_message = item.get('errorMessage', {}).get('S', 'No error message')
                    recent_failures.append({
                        'created_at': created_at,
                        'error': error_message[:200]
                    })
            elif status in ['RUNNING', 'PENDING']:
                running += 1
        
        print(f"\nMessage Status:")
        print(f"  COMPLETED: {completed}")
        print(f"  FAILED:    {failed}")
        print(f"  RUNNING:   {running}")
        
        if recent_failures:
            print(f"\n❌ Recent failures found:")
            for failure in recent_failures[:3]:
                print(f"\n  {failure['created_at']}")
                print(f"  {failure['error']}")
        
        if failed > 0:
            return {"status": "FAIL", "failed_count": failed, "completed_count": completed}
        elif completed > 0:
            print("\n✅ Console chat messages completing successfully!")
            return {"status": "PASS", "completed_count": completed}
        else:
            print("\n⚠️  No completed messages to verify")
            return {"status": "WARNING", "reason": "No completed messages"}
            
    except Exception as e:
        print(f"❌ Error checking messages: {e}")
        return {"status": "ERROR", "error": str(e)}

def main():
    print("Web Console Chat Production Test")
    print("=" * 80)
    print()
    
    results = {
        "iam": check_lambda_iam_permissions(),
        "logs": check_cloudwatch_logs(),
        "messages": check_recent_messages()
    }
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    all_pass = all(r.get("status") == "PASS" for r in results.values())
    any_fail = any(r.get("status") == "FAIL" for r in results.values())
    
    print(f"\nIAM Permissions:  {results['iam']['status']}")
    print(f"CloudWatch Logs:  {results['logs']['status']}")
    print(f"Recent Messages:  {results['messages']['status']}")
    
    if all_pass:
        print("\n✅ ✅ ✅  ALL CHECKS PASSED  ✅ ✅ ✅")
        print("\nWeb console chat is working correctly!")
        sys.exit(0)
    elif any_fail:
        print("\n❌ FAILURES DETECTED")
        print("\nThe web console chat issue persists.")
        print("\nNext steps:")
        print("1. Verify the fix commit (0c39cbb) is deployed to production")
        print("2. Check Amplify deployment status")
        print("3. Review CloudWatch logs for detailed errors")
        sys.exit(1)
    else:
        print("\n⚠️  WARNINGS - UNABLE TO FULLY VERIFY")
        print("\nSome checks could not complete. Manual testing recommended.")
        sys.exit(2)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
