# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Python Imports - License: https://docs.python.org/3/license.html
import os
import json
import urllib3 
from urllib.parse import unquote_plus
http = urllib3.PoolManager()

# AWS SDK Imports
import boto3
from botocore.exceptions import ClientError

AWS_REGION = os.environ["AWS_REGION"]
CONNECT_CLIENT = boto3.client("connect", region_name=AWS_REGION)
WISDOM_CLIENT = boto3.client("wisdom", region_name=AWS_REGION)
S3_CLIENT = boto3.client('s3', region_name=AWS_REGION)

# AWS Lambda Environment Variables
KNOWLEDGE_BASE_ARN = os.getenv('KNOWLEDGE_BASE_ARN')
KNOWLEDGE_BASE_ID = KNOWLEDGE_BASE_ARN.split('/')[-1]

# This AWS Lambda function will handle the synchronization of Amazon S3 files with Amazon Connect Wisdom
# This main function triggered by an SQS event (S3 Event Notification -> SQS)
def lambda_handler(event, context):
    # Initially, event is a dictionary. Use json.dumps(x) to convert JSON -> String. Use json.loads(x) to convert String -> JSON
    print("Event Recieved (String): ", json.dumps(event))
    print("KnowledgeBase ARN: ", KNOWLEDGE_BASE_ARN)

    # Parse the SQS Event Body. (Initially, sqsEventBody is a string, needs json.loads() to convert to dictionary)
    sqsEventBody = event["Records"][0]["body"] # print("SQS Event Body (String): ", sqsEventBody)
    sqsEventBody = json.loads(sqsEventBody) # print("SQS Event Body (Dictionary): ", sqsEventBody)

    # Handle S3 Test Events
    if "Event" in sqsEventBody:
        print("Amazon S3 -> SQS Event Recieved: ", sqsEventBody["Event"]) 
        if sqsEventBody["Event"] == "s3:TestEvent":
            print("S3 Test Event Recieved, no action taken")
            return
        
    # Parse Incoming SQS Event - S3 Event Notification
    if "Records" in sqsEventBody:
        s3EventBody = sqsEventBody["Records"][0]
        # print("S3 Event Body (Dictionary): ", s3EventBody)
        print("S3 Event Body (String): ", json.dumps(s3EventBody))
        
        eventName = s3EventBody["eventName"]
        print("Amazon S3 -> SQS Event Recieved: ", eventName)
        
        s3Data = s3EventBody["s3"]
        print("S3 Data: ", s3Data)

        # Step 2.1: Parse S3 Event Body
        bucket = s3Data["bucket"]["name"]
        
        # Preprocess S3 Key from SQS Event to handle case where spaces exist in the file name
        raw_key = s3Data["object"]["key"]
        key = unquote_plus(raw_key) 
        print("Original Key: ", raw_key, ", Parsed Key: ", key)
        version = s3Data["object"]["versionId"]
        print("Bucket: ", bucket, " Key: ", key, " Version: ", version)

        # Search for existing Wisdom Content with the same Key
        searchWisdomContentResponse = wisdomSearchContent(KNOWLEDGE_BASE_ID, key)["data"]
        print("Existing Wisdom Content (Wisdom SearchContent): ", json.dumps(searchWisdomContentResponse))

        # Handle S3 Bucket Object Notification Events (Create/Update/Delete)
        # Case 1: S3 Event Type is ObjectCreated (Create/Update)
        if "ObjectCreated" in eventName:
            print("START processing S3:ObjectCreated")

            # Get S3 Object for CREATE or UPDATE
            # S3 Get Object API Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/get_object.html#
            s3GetObjectResponse = s3GetObject(bucket, key) # versionId=version
            if len(s3GetObjectResponse) == 0:
                print("Object: ", key, " does not exist in Amazon S3 bucket: ", bucket, " nothing to create/update")
                return
            
            # If S3 Get Object Response is not None, then there is a valid object in the Amazon S3 Bucket with the provided Key.
            # Upload S3 Object to Wisdom KnowledgeBase using Wisdom StartContentUpload API
            wisdomStartContentUploadResponse = wisdomStartContentUpload(KNOWLEDGE_BASE_ID, s3GetObjectResponse)
            print("START - Wisdom Content Upload Response: ", json.dumps(wisdomStartContentUploadResponse))
            uploadId = wisdomStartContentUploadResponse["data"]

            # Case 1.1: UPDATE - If there is an existing item found in the Wisdom KnowledgeBase, update it.
            if len(searchWisdomContentResponse):
                print("UPDATE - Object: ", key, " already exists in Wisdom KnowledgeBase, updating Wisdom content")
                print("ExistingWisdomContent: ", searchWisdomContentResponse[0])
                updateContentResponse = wisdomUpdateContent(knowledgeBaseId=KNOWLEDGE_BASE_ID, uploadId=uploadId, bucketName=bucket, objectKey=key, rawObjectKey=raw_key, existingWisdomContent=searchWisdomContentResponse)
                responseData = json.dumps(updateContentResponse, sort_keys=True, default=str)
                
                # Return Response Data
                print("SUCCESS - Wisdom UpdateContent Response: ", responseData)
                return {"status": "SUCCESS", "data": responseData}
            # CASE 1.2: CREATE - If there is no existing Wisdom Content for the S3 Object, create new Wisdom Content
            else:
                print("CREATE - Object: ", key, " does not exist in KnowledgeBase, creating Wisdom content")
                createContentResponse = wisdomCreateContent(knowledgeBaseId=KNOWLEDGE_BASE_ID, uploadId=uploadId, bucketName=bucket, objectKey=key, rawObjectKey=raw_key)
                responseData = json.dumps(createContentResponse, sort_keys=True, default=str)
                
                # Return Response Data
                print("SUCCESS - Wisdom CreateContent Response: ", responseData)
                return {"status": "SUCCESS", "data": responseData}

        # Case 2: S3 Event Type is ObjectRemoved (Delete)
        elif "ObjectRemoved" in eventName:
            print("START processing S3:ObjectRemoved")
            # Case 2.1: On DELETE - IF Object does exist in KnowledgeBase, process deletion
            if len(searchWisdomContentResponse):
                print("DELETE - Object: ", key, " exists in KnowledgeBase, deleting Wisdom content.")
                print("START DeleteContent: ", searchWisdomContentResponse[0], " from KnowledgeBase: ", KNOWLEDGE_BASE_ID)
                try:
                    WISDOM_CLIENT.delete_content(
                        knowledgeBaseId = KNOWLEDGE_BASE_ID,
                        contentId = searchWisdomContentResponse[0]["contentId"],
                    )
                    print("SUCCESS - Wisdom DeleteContent Response: ", json.dumps(searchWisdomContentResponse[0]["title"]))
                    return {"status": "SUCCESS", "data": "Wisdom Content Successfully Deleted"}
                except ClientError as e:
                    print("Client Error - Wisdom DeleteContent: ", str(e))
                    return {"status": "CLIENT_ERROR", "data": str(e)}
                except Exception as ex:
                    print("Exception - Wisdom DeleteContent: ", str(ex))
                    return {"status": "EXCEPTION", "data": str(ex)}

            # Case 2.2: On DELETE - IF Object does NOT exist in KnowledgeBase, return None
            else:
                print("DELETE - Object: ", key, " does not exist in KnowledgeBase, nothing to delete")
                return
        # Case 3: Unsupported S3 Event Type
        else:
            print("Event not supported: ", eventName)
            return

# Search Amazon Connect Wisdom Knowledge Base for Content (Accepts either Instance ID or ARN)
# Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/wisdom/client/search_content.html#
# CLI Example: aws wisdom search-content --knowledge-base-id arn:aws:wisdom:REGION:ACCOUNTID:knowledge-base/KNOWLEDGEBASEID --search-expression "{"filters": [{"field": "NAME", "operator": "EQUALS","value": "sample/password-reset.html"}]}
def wisdomSearchContent(knowledgeBaseId, key):
    try:
        search = WISDOM_CLIENT.search_content(
            knowledgeBaseId = knowledgeBaseId,
            maxResults = 100,
            searchExpression={
                "filters": [{
                    "field": "NAME",
                    "operator": "EQUALS",
                    "value": key
                }]
            }
        )
        print("SUCCESS - Wisdom SearchContent - Key: ", key, " Results: ", search)
        return {"status": "SUCCESS", "data": search["contentSummaries"]}
    except ClientError as e:
        print("Client Error - Wisdom SearchContent: ", str(e))
        return {"status": "CLIENT_ERROR", "data": str(e)}
    except Exception as ex:
        print("Exception - Wisdom SearchContent: ", str(ex))
        return {"status": "EXCEPTION", "data": str(ex)}

# Amazon S3 Get Object: If Object Exists, return S3 Object. Else, return None.
# Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.get_object    
def s3GetObject(bucketName, objectKey):
    try:
        s3Object = S3_CLIENT.get_object(Bucket=bucketName, Key=objectKey)
        print("S3 Object: ", s3Object)
        return s3Object
    except ClientError as e:
        print("Client Error: ", str(e))
        return {"status": "CLIENT_ERROR", "data": str(e)}
    except Exception as ex:
        print("Error: ", str(ex))
        return {"status": "EXCEPTION", "data": str(ex)}

# Wisdom StartContentUpload: Initiate Wisdom Content Upload of S3 Object, returns uploadId
# Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/wisdom/client/start_content_upload.html
def wisdomStartContentUpload(knowledgeBaseId, s3Object):
    print("Wisdom StartContentUpload S3 Object")
    print("S3 Object: ", s3Object)
    print("Content Type: ", s3Object["ContentType"])
    print("Knowledge Base ID/ARN: ", knowledgeBaseId)

    try:
        response = WISDOM_CLIENT.start_content_upload(
            contentType = s3Object["ContentType"],
            knowledgeBaseId = knowledgeBaseId
        )
        print("Wisdom StartContentUpload Response: ", response)
        print("Upload ID: ", response["uploadId"])
        print("Upload Details: ", response)

        # Make an HTTP Request to put Object Body to Content Upload URL
        s3StreamingBody = s3Object['Body']
        streamingBodyRead = s3StreamingBody.read()
        httpResponse = http.request('PUT', response["url"], headers=response["headersToInclude"], body=streamingBodyRead)
        
        # Return Response Data
        print("Wisdom StartContentUpload Response: ", response)
        return {"status": "SUCCESS", "data": response["uploadId"]}
    except ClientError as e:
        print("Wisdom StartContentUpload Client Error: ", str(e))
        return {"status": "CLIENT_ERROR", "data": str(e)}
    except Exception as ex:
        print("Wisdom StartContentUpload Exception: ", str(ex))
        return {"status": "EXCEPTION", "data": str(ex)}

# Amazon Connect Wisdom Create Knowledge Base Content
# Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/wisdom/client/create_content.html
# rawKey is the raw generated Amazon S3 Key (before parsing). This is necessary for LinkOutUri to work properly.
def wisdomCreateContent(knowledgeBaseId, uploadId, bucketName, objectKey, rawObjectKey):
    try:
        # Start Wisdom CreateContent
        response = WISDOM_CLIENT.create_content(
            knowledgeBaseId = knowledgeBaseId,
            name=objectKey, # Must be unique.
            # title=objectKey.split("/")[1].split(".")[0], # Optional: Title is equal to file name without extension or folder prefix.
            uploadId = uploadId,
            overrideLinkOutUri=f"https://{bucketName}.s3.amazonaws.com/{rawObjectKey}", # Set Link Out URL on Wisdom Tab
            metadata = {
                "sourceS3Bucket": bucketName,
                "sourceS3Key": objectKey,
                # "sourceS3Version": "",
                "rawObjectKey": rawObjectKey,
                "s3URL": f"https://{bucketName}.s3.amazonaws.com/{rawObjectKey}"
            }
        )
        # Note: Since "response[content]" contains datetime object, cannot cast it to a string using json.dumps() or str()
        print("SUCCESS - Wisdom CreateContent Response: ", response)
        print("Content ID: ", response["content"]["contentId"])
        return response["content"]
    except ClientError as e:
        print("Client Error: ", str(e))
        return {"status": "CLIENT_ERROR", "data": str(e)}
    except Exception as ex:
        print("Exception - Wisdom CreateContent: ", str(ex))
        return {"status": "EXCEPTION", "data": str(ex)}

# Amazon Connect Wisdom Update Knowledge Base Content (Accepts either Knowledgebase ID or ARN)
# Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/wisdom/client/update_content.html
# rawObjectKey is the Amazon S3 Key (before parsing). This is necessary for LinkOutUri to work properly.
def wisdomUpdateContent(knowledgeBaseId, uploadId, bucketName, objectKey, rawObjectKey, existingWisdomContent):
    try:
        # Start Wisdom UpdateContent (Unlike CreateContent, UpdateContent only has a parameter 'title', but not 'name'.)
        response = WISDOM_CLIENT.update_content(
            knowledgeBaseId = knowledgeBaseId,
            title=objectKey, # Set title to Object Key.
            contentId = existingWisdomContent[0]["contentId"],
            revisionId = existingWisdomContent[0]["revisionId"],
            uploadId = uploadId,
            overrideLinkOutUri=f"https://{bucketName}.s3.amazonaws.com/{rawObjectKey}", # Set Link Out URL on Wisdom Tab
            metadata = {
                "sourceS3Bucket": bucketName,
                "sourceS3Key": objectKey,
                # "sourceS3Version": "",
                "rawObjectKey": rawObjectKey,
                "s3URL": f"https://{bucketName}.s3.amazonaws.com/{rawObjectKey}"
            }
        )
        # Note: Since "response[content]" contains datetime object, cannot cast it to a string using json.dumps() or str()
        print("SUCCESS - Wisdom UpdateContent Response: ", response)
        return response["content"]
    except ClientError as e:
        print("Client Error - Wisdom UpdateContent: ", str(e))
        return str(e)
    except Exception as ex:
        print("Exception - Wisdom UpdateContent: ", str(ex))
        return str(ex)

# Amazon Connect Wisdom Delete Knowledge Base Content (Accepts either Knowledgebase ID or ARN)
# Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/wisdom/client/delete_content.html
def wisdomDeleteContent(knowledgeBaseId, existingWisdomContent):
    try:
        WISDOM_CLIENT.delete_content(
            knowledgeBaseId = knowledgeBaseId,
            contentId = existingWisdomContent[0]["contentId"],
        )
        print("SUCCESS - Wisdom DeleteContent Response: ", json.dumps(existingWisdomContent[0]["title"]))
        return {"status": "SUCCESS", "data": "Wisdom Content Successfully Deleted"}
    except ClientError as e:
        print("Client Error - Wisdom DeleteContent: ", str(e))
        return str(e)
    except Exception as ex:
        print("Exception - Wisdom DeleteContent: ", str(ex))
        return str(ex)
