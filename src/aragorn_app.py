"""aragorn server."""
import asyncio
import json
import os
import logging.config
from pathlib import Path

import pkg_resources
import reasoner_pydantic
import yaml
import aio_pika
from aio_pika.abc import AbstractRobustConnection
from aio_pika.pool import Pool
import random
import string

# from pamqp import specification as spec
from enum import Enum
from reasoner_pydantic import Query as PDQuery, AsyncQuery as PDAsyncQuery, Response as PDResponse, QNode
from pydantic import BaseModel
from fastapi import Body, FastAPI, BackgroundTasks
from reasoner_pydantic.shared import KnowledgeType

from src.openapi_constructor import construct_open_api_schema
from src.common import async_query, sync_query
from src.default_queries import default_input_sync, default_input_async

# declare the FastAPI details
ARAGORN_APP = FastAPI(title="ARAGORN")

# Set up default logger.
with open(Path(__file__).parent / "resources" / "logging.yml", "r") as f:
    config = yaml.safe_load(f.read())

# declare the log directory
log_dir = "./logs"

# make the directory if it does not exist
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# create a configuration for the log file
config["handlers"]["file"]["filename"] = os.path.join(log_dir, "aragorn.log")
log_level = os.getenv("LOG_LEVEL", "DEBUG")
config["handlers"]["console"]["level"] = log_level
config["handlers"]["file"]["level"] = log_level
config["loggers"]["src"]["level"] = log_level
config["loggers"]["aio_pika"]["level"] = log_level

# load the log config
logging.config.dictConfig(config)

# create a logger
logger = logging.getLogger(__name__)

# declare the directory where the async data files will exist
queue_file_dir = "./queue-files"

# make the directory if it does not exist
if not os.path.exists(queue_file_dir):
    os.makedirs(queue_file_dir)

# declare the types of answer coalesce methods
class MethodName(str, Enum):
    all = "all"
    none = "none"
    graph = "graph"
    ontology = "ontology"
    property = "property"


# define the default request bodies
default_request_sync: Body = Body(default=default_input_sync, embed=False)
default_request_async: Body = Body(default=default_input_async, example=default_input_async)

# get the queue connection params
q_username = os.environ.get("RABBITMQ_DEFAULT_USER", "guest")
q_password = os.environ.get("RABBITMQ_DEFAULT_PASS", "guest")
q_host = os.environ.get("RABBITMQ_HOSTNAME", "127.0.0.1")


loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


async def get_connection() -> AbstractRobustConnection:
    return await aio_pika.connect_robust(f"amqp://{q_username}:{q_password}@{q_host}/")


connection_pool: Pool = Pool(get_connection, max_size=4, loop=loop)


async def get_channel() -> aio_pika.Channel:
    async with connection_pool.acquire() as connection:
        return await connection.channel()


channel_pool: Pool = Pool(get_channel, max_size=10, loop=loop)


# Create a async class
class AsyncReturn(BaseModel):
    description: str


# async entry point
@ARAGORN_APP.post("/asyncquery", tags=["ARAGORN"], response_model=AsyncReturn)
async def async_query_handler(
    background_tasks: BackgroundTasks, request: PDAsyncQuery = default_request_async, answer_coalesce_type: MethodName = MethodName.all
):
    """
    Performs an asynchronous query operation which compiles data from numerous ARAGORN ranking agent services.
    The services are called in the following order, each passing their output to the next service as an input:

    Strider -> (optional) Answer Coalesce -> ARAGORN-Ranker:omnicorp overlay -> ARAGORN-Ranker:weight correctness -> ARAGORN-Ranker:score
    """
    return await async_query(background_tasks, request, answer_coalesce_type, logger, "ARAGORN")


# synchronous entry point
@ARAGORN_APP.post("/query", tags=["ARAGORN"], response_model=PDResponse, response_model_exclude_none=True, status_code=200)
async def sync_query_handler(query: PDQuery = default_request_sync, answer_coalesce_type: MethodName = MethodName.all):
    """Performs a synchronous query operation which compiles data from numerous ARAGORN ranking agent services.
    The services are called in the following order, each passing their output to the next service as an input:

    Strider -> (optional) Answer Coalesce -> ARAGORN-Ranker:omnicorp overlay -> ARAGORN-Ranker:weight correctness -> ARAGORN-Ranker:score
    """

    logger.debug(f"query: {query.json()}")

    potential_object = list(
        filter(
            lambda x: "biolink:treats" in x[1].predicates and x[1].knowledge_type.inferred is KnowledgeType.inferred, query.message.query_graph.edges.items()
        )
    )
    obj = potential_object[0][1].object
    logger.debug(f"obj: {obj}")

    response = None
    if obj is not None:

        subject_identifier_nodes = list(filter(lambda x: x[0] == obj, query.message.query_graph.nodes.items()))
        subject_identifier_node_ids_value = subject_identifier_nodes[0][1].ids[0]
        logger.debug(f"subject_identifier_node_ids_value: {subject_identifier_node_ids_value}")

        path_a_query_file = Path(__file__).parent / "resources" / "path_a.json"
        with open(path_a_query_file, "r") as rsc:
            path_a_query_file_text = rsc.read()
            path_a_query_file_text = path_a_query_file_text.replace("CURIE_TOKEN", subject_identifier_node_ids_value)
        logger.debug(f"path_a_query_file_text: {path_a_query_file_text}")
        path_a_query = reasoner_pydantic.message.Query.parse_raw(path_a_query_file_text)

        path_a_response = await sync_query(path_a_query.dict(), answer_coalesce_type, logger, "ARAGORN")
        path_a_response_json = str(path_a_response.body)
        logger.debug(f"path_a_response_json: {path_a_response_json}")

        path_b_query_file = Path(__file__).parent / "resources" / "path_b.json"
        with open(path_b_query_file, "r") as rsc:
            path_b_query_file_text = rsc.read()
            path_b_query_file_text = path_b_query_file_text.replace("CURIE_TOKEN", subject_identifier_node_ids_value)
        logger.debug(f"path_b_query_file_text: {path_b_query_file_text}")
        path_b_query = reasoner_pydantic.message.Query.parse_raw(path_b_query_file_text)

        secondary_response = await sync_query(path_b_query.dict(), answer_coalesce_type, logger, "ARAGORN")
        secondary_response_json = str(secondary_response.body)
        logger.debug(f"secondary_response_json: {secondary_response_json}")

    else:
        response = await sync_query(query, answer_coalesce_type, logger, "ARAGORN")

    return response


@ARAGORN_APP.post("/callback/{guid}", tags=["ARAGORN"], include_in_schema=False)
async def subservice_callback(response: PDResponse, guid: str) -> int:
    """
    Receives asynchronous message requests from an ARAGORN subservice callback

    :param response:
    :param guid:
    :return:
    """
    # init the return html status code
    ret_val: int = 200

    logger.info(f"{guid}: Receiving sub-service callback")
    # logger.debug(f'{guid}: The sub-service response: {response.json()}')

    try:
        async with channel_pool.acquire() as channel:
            await channel.get_queue(guid, ensure=True)

            # create a file path/name
            fname = "".join(random.choices(string.ascii_lowercase, k=12))
            file_name = f"{queue_file_dir}/{guid}-{fname}-async-data.json"

            # save the response data to a file
            with open(file_name, "w") as data_file:
                data_file.write(response.json())

            # publish what was received for the sub-service. post the file name for the queue handler
            publish_val = await channel.default_exchange.publish(aio_pika.Message(body=file_name.encode()), routing_key=guid)

            if publish_val:
                logger.info(f"{guid}: Callback message published to queue.")
            else:
                logger.error(f"{guid}: Callback message publishing to queue failed, type: {type(publish_val)}")
            # if isinstance(publish_val, spec.Basic.Ack):
            #    logger.info(f'{guid}: Callback message published to queue.')
            # else:
            #    # set the html error code
            #    ret_val = 422
            #    logger.error(f'{guid}: Callback message publishing to queue failed, type: {type(publish_val)}')

    except Exception as e:
        logger.exception(f"Exception detected while handling sub-service callback using guid {guid}", e)
        # set the html status code
        ret_val = 500

    # return the response code
    return ret_val


@ARAGORN_APP.post("/aragorn_callback", tags=["ARAGORN"], include_in_schema=False)
async def receive_aragorn_async_response(response: PDResponse) -> int:
    """
    An endpoint for receiving the aragorn callback results. normally used in
    debug mode to verify the round trip insuring that the data is viable to a real client.
    """
    if hasattr(response, "pid"):
        pid = response.pid
    else:
        pid = "no PID"

    # save it to the log
    logger.debug(f"{pid}: ARAGORN async callback received.")

    # get the response in a dict
    # result = response.json()
    # logger.debug(f'{pid}: ARAGORN callback received. message {result}')

    # return the response code
    return 200


ARAGORN_APP.openapi_schema = construct_open_api_schema(ARAGORN_APP, prefix="aragorn", description="ARAGORN: A fully-federated Translator ARA.")
