import logging

import requests

from rasa.rasa_intent import RasaIntent

logger = logging.getLogger(__name__)
# 意图到mcp或java的调用
def parseIntents(objs: list):

    result = []
    base_url = "http://192.168.0.158:28080/ai/"
    payload = {}
    for obj in objs:
        logger.info(f"parseIntent: {obj}")
        path = ''
        if obj.intent is not None:
            if obj.intent == 4:
                path = 'four'
                payload = obj.params
            elif obj.intent == 5:
                path = 'five'
            elif obj.intent == 6:
                path = 'six'
            url = f"{base_url}{path}"
            response = requests.post(url, params=payload)
            logger.info(f"response: {response.text}")
        else:
            logger.info(f"to llm {obj.message}")


