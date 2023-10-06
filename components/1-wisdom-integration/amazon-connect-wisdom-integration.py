# © 2023 Amazon Web Services, Inc. or its affiliates. All Rights Reserved.
# This AWS Content is provided subject to the terms of the AWS Customer Agreement available at
# http://aws.amazon.com/agreement or other written agreement between Customer and either
# Amazon Web Services, Inc. or Amazon Web Services EMEA SARL or both.
# Version Info: 2023.09.25
# This AWS Lambda Function will:
# 1. Check for Existing Amazon Connect Integration Associations - Wisdom.
# **NOTE**: If the Connect Instance has an existing Integration Association, the Integration Association will be deleted and replaced with the new Integration Association.
# 2. Create an Amazon Connect Integration Association with an Amazon Connect Wisdom (Assistant and KnowledgeBase).

# Python License: https://docs.python.org/3/license.html
import os
import json

# CloudFormation Response only available if deployed inline.
# import cfnresponse # Apache License: https://pypi.org/project/cfnresponse/
import urllib3 # MIT License: https://pypi.org/project/urllib3/
http = urllib3.PoolManager()
SUCCESS = "SUCCESS"
FAILED = "FAILED"

# AWS SDK Imports
import boto3
from botocore.exceptions import ClientError

CONNECT_CLIENT = boto3.client('connect')
WISDOM_CLIENT = boto3.client('wisdom')

# STACK_UUID: Substring of CloudFormation StackID. Used to identify and tag resources
STACK_UUID = os.environ["STACK_UUID"] 

# Description: IF THE CONNECT INSTANCE HAS AN EXISTING INTEGRATION, REMOVE the INTEGRATION ASSOCIATION, REPLACE WITH NEW.
def lambda_handler(event, context):
    print("Event Recieved: ", json.dumps(event))
    print("Request Type:", event['RequestType'])
    print("Resource Properties: ", json.dumps(event["ResourceProperties"]))

    # Define variables from Custom Resource Event Data
    PHYSICAL_RESOURCE_ID = event["ResourceProperties"]["ServiceToken"]
    # STACK_UUID = event["ResourceProperties"]["STACK_UUID"] # Substring of CloudFormation StackID. Used to identify and tag resources"
    INSTANCE_ARN = event["ResourceProperties"]["INSTANCE_ARN"] # To get InstanceId: INSTANCE_ARN.split("/")[1]
    WISDOM_ASSISTANT_ARN = event["ResourceProperties"]["WISDOM_ASSISTANT_ARN"] 
    WISDOM_KNOWLEDGE_BASE_ARN = event["ResourceProperties"]["WISDOM_KNOWLEDGE_BASE_ARN"]

    # Check for existing Integrations: List Integration Association - Wisdom Assistant / Knowledge Base
    # Full Assistant/KnowledgeBase Integration Association Object: [{'IntegrationAssociationId': 'string', 'IntegrationAssociationArn': 'string', 'InstanceId': 'string', 'IntegrationType': 'WISDOM_ASSISTANT', 'IntegrationArn': 'string'}]
    connectWisdomAssistantIntegration = listIntegrationAssociations(instanceId=INSTANCE_ARN, integrationType="WISDOM_ASSISTANT")
    connectWisdomKnowledgeBaseIntegration = listIntegrationAssociations(instanceId=INSTANCE_ARN, integrationType="WISDOM_KNOWLEDGE_BASE")
    print("Connect Integration - Wisdom Assistant ", json.dumps(connectWisdomAssistantIntegration))    
    print("Connect Integration - Wisdom Knowledgebase ", json.dumps(connectWisdomKnowledgeBaseIntegration))

    # Define shared ResponseData Expected by CloudFormation Response:
    responseData = {
        "Connect_WisdomAssistant_IntegrationAssociationARN": "", # Connect Integration Association - Wisdom Assistant
        "Connect_WisdomKnowledgeBase_IntegrationAssociationARN": "", # Connect Integration Association - Wisdom KnowledgeBase
        "Wisdom_Assistant_ARN": "", # Amazon Connect Integration Association - Wisdom Assistant
        "Wisdom_KnowledgeBase_ARN": "", # Amazon Connect Integration Association - Wisdom KnowledgeBase
    }

    # Case 1: CloudFormation Stack sends Create or Update Event.
    if event["RequestType"] == "Create" or event["RequestType"] == "Update":
        # Case 1: If the Connect Instance has existing Wisdom Integrations (both Assistant and KnowledgeBase) return those values.
        if len(connectWisdomAssistantIntegration) and len(connectWisdomKnowledgeBaseIntegration):
            # Roadmap: Delete Existing Integration Associations, create new Integration Associations with resources.
            print("Connect Instance: ", INSTANCE_ARN, " has existing Wisdom integrations.")

            # Return previous Integration Association Data
            responseData["Previous_Connect_WisdomAssistant_IntegrationAssociation"] = str(connectWisdomAssistantIntegration[0])
            responseData["Previous_Wisdom_Assistant_ARN"] = str(connectWisdomAssistantIntegration[0]['IntegrationArn'])
            responseData["Previous_Connect_WisdomKnowledgeBase_IntegrationAssociation"] = str(connectWisdomKnowledgeBaseIntegration[0])
            responseData["Previous_Wisdom_KnowledgeBase_ARN"] = str(connectWisdomKnowledgeBaseIntegration[0]['IntegrationArn'])
        
            deleteConnectWisdomAssistantIntegration = deleteIntegrationAssociation(instanceId=INSTANCE_ARN, integrationAssociationId=connectWisdomAssistantIntegration[0]['IntegrationAssociationId'])
            print("Delete Complete: Amazon Connect Integration Association - Wisdom Assistant: ", connectWisdomAssistantIntegration[0]['IntegrationAssociationId'])

            deleteConnectWisdomKnowledgeBaseIntegration = deleteIntegrationAssociation(instanceId=INSTANCE_ARN, integrationAssociationId=connectWisdomKnowledgeBaseIntegration[0]['IntegrationAssociationId'])
            print("Delete Complete: Amazon Connect Integration Association - Wisdom KnowledgeBase: ", connectWisdomKnowledgeBaseIntegration[0]['IntegrationAssociationId'])
        else:
            print("Connect Instance: ", INSTANCE_ARN, " has no existing Wisdom integrations.")
        
        # Step 2: Create new Integration Associations with provided Wisdom Assistant and Knowledge Base
        # At this point, Connect Instance has no existing Wisdom Integrations.
        if len(WISDOM_ASSISTANT_ARN) > 0:
            connectWisdomAssistantIntegration = createIntegrationAssociation(INSTANCE_ARN, WISDOM_ASSISTANT_ARN, 'WISDOM_ASSISTANT')
            print("Connect Integration - Wisdom Assistant. Create Integration Association Response: ", connectWisdomAssistantIntegration)
            if connectWisdomAssistantIntegration['status'] == "SUCCESS":
                responseData["Connect_WisdomAssistant_IntegrationAssociationARN"] = connectWisdomAssistantIntegration['IntegrationAssociationArn']
                responseData["Wisdom_Assistant_ARN"] = WISDOM_ASSISTANT_ARN
        else:
            print("Wisdom Assistant ARN not provided. Skipping Integration Association Creation.")

        if len(WISDOM_KNOWLEDGE_BASE_ARN) > 0:
            connectWisdomKnowledgeBaseIntegration = createIntegrationAssociation(INSTANCE_ARN, WISDOM_KNOWLEDGE_BASE_ARN, 'WISDOM_KNOWLEDGE_BASE')
            print("Connect Integration - Wisdom KnowledgeBase. Create Integration Association Response: ", connectWisdomKnowledgeBaseIntegration)
            if connectWisdomKnowledgeBaseIntegration['status'] == "SUCCESS":
                responseData["Connect_WisdomKnowledgeBase_IntegrationAssociationARN"] = connectWisdomKnowledgeBaseIntegration['IntegrationAssociationArn']
                responseData["Wisdom_KnowledgeBase_ARN"] = WISDOM_KNOWLEDGE_BASE_ARN
        else:
            print("Wisdom KnowledgeBase ARN not provided. Skipping Integration Association Creation.")

        # Send CFN Response
        print("Create/Update - Wisdom Integration Handler Response: ", json.dumps(responseData))
        send(event, context, "SUCCESS", responseData, PHYSICAL_RESOURCE_ID)
        return responseData
    
    # CloudFormation Stack sends DELETE signal - Delete Connect Integration Associations.
    # DELETE - ORDER OF OPERATIONS: 1) Connect-Assistant Integration, 2) Connect-Knowledgebase Integration, 3) Wisdom Assistant-Knowledgebase Association, 4) Wisdom Assistant, 5) Wisdom Knowledgebase
    if event["RequestType"] == "Delete":
        # Case 1: If the Connect Instance has Wisdom Integration Associations (WISDOM_ASSISTANT, WISDOM_KNOWLEDGE_BASE), delete resources.
        if len(connectWisdomAssistantIntegration):
            response = deleteIntegrationAssociation(INSTANCE_ARN, connectWisdomAssistantIntegration[0]["IntegrationAssociationId"])
            print("Connect Integration - Wisdom Assistant. Delete Integration Association Response: ", str(response))

        if len(connectWisdomKnowledgeBaseIntegration):
            response = deleteIntegrationAssociation(INSTANCE_ARN, connectWisdomKnowledgeBaseIntegration[0]["IntegrationAssociationId"])
            print("Connect Integration - Wisdom KnowledgeBase. Delete Integration Association Response: ", str(response))
        
        # Send CFN Response
        print("Delete - Wisdom Integration Handler Response: ", json.dumps(responseData))
        send(event, context, "SUCCESS", responseData, PHYSICAL_RESOURCE_ID)
        return responseData

# List Amazon Connect Instance Integration Associations (Accepts either Instance ID or ARN)
# https://docs.aws.amazon.com/connect/latest/APIReference/API_ListIntegrationAssociations.html
def listIntegrationAssociations(instanceId, integrationType):
    CONNECT_CLIENT = boto3.client('connect')
    try:
        response = CONNECT_CLIENT.list_integration_associations(
            InstanceId=instanceId,
            IntegrationType=integrationType
        )
        return response["IntegrationAssociationSummaryList"]
    except ClientError as e:
        print(e)
        return {'status': "CLIENT_ERROR", 'Message': str(e)}
    except Exception as ex:
        print(ex)
        return {'status': "EXCEPTION", 'Message': str(ex)}

# Integrates a WISDOM_KNOWLEDGE_BASE or WISDOM_ASSISTANT with an Amazon Connect Instance
# https://docs.aws.amazon.com/connect/latest/APIReference/API_CreateIntegrationAssociation.html
def createIntegrationAssociation(instanceId, integrationArn, integrationType):
    print("Creating Integration Association between Connect Instance: ", instanceId, " and the Wisdom Resource: ", integrationArn, " with Integration Type: ", integrationType, " and UUID Tag: ", STACK_UUID)
    try:
        response = CONNECT_CLIENT.create_integration_association(
            InstanceId = instanceId,
            IntegrationArn = integrationArn,
            IntegrationType = integrationType,
            Tags={ "UUID": STACK_UUID }
        )
        response["status"] = "SUCCESS"
        return response
    except ClientError as e:
        return {'status': "CLIENT_ERROR", 'Message': str(e)}
    except Exception as ex:
        return {'status': "EXCEPTION", 'Message': str(ex)}

# Delete a Connect - Wisdom Integration Association (Assistant or KnowledgeBase)
# https://docs.aws.amazon.com/connect/latest/APIReference/API_DeleteIntegrationAssociation.html
def deleteIntegrationAssociation(instanceId, integrationAssociationId):
    print("Deleting Integration Association between Connect Instance: ", instanceId, " and the Wisdom Resource: ", integrationAssociationId)
    try:
        CONNECT_CLIENT.delete_integration_association(InstanceId=instanceId, IntegrationAssociationId=integrationAssociationId)
        return {'status': "SUCCESS", 'Message': str("Integration Association, " + integrationAssociationId + ", deleted successfully")}
    except ClientError as e:
        return {'status': "CLIENT_ERROR", 'Message': str(e)}
    except Exception as ex:
        return {'status': "EXCEPTION", 'Message': str(ex)}

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# CloudFormation Response Helper Function: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-lambda-function-code-cfnresponsemodule.html
def send(event, context, responseStatus, responseData, physicalResourceId=None, noEcho=False, reason=None):
    responseUrl = event['ResponseURL']
    print(responseUrl)
    
    responseBody = {
        'Status' : responseStatus,
        'Reason' : reason or "See the details in CloudWatch Log Stream: {}".format(context.log_stream_name),
        'PhysicalResourceId' : physicalResourceId or context.log_stream_name,
        'StackId' : event['StackId'],
        'RequestId' : event['RequestId'],
        'LogicalResourceId' : event['LogicalResourceId'],
        'NoEcho' : noEcho,
        'Data' : responseData
    }
    json_responseBody = json.dumps(responseBody)
    print("Response body: ", json_responseBody)

    headers = {
        'content-type' : '',
        'content-length' : str(len(json_responseBody))
    }

    try:
        response = http.request('PUT', responseUrl, headers=headers, body=json_responseBody)
        print("Status code:", response.status)
    except Exception as e:
        print("send(..) failed executing http.request(..):", e)