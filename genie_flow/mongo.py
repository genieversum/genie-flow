from loguru import logger

from pymongo import MongoClient
from dependency_injector.wiring import inject, Provide

from genie_flow.containers.perm_persistence import (
    GenieFlowPermanentPersistenceContainer,
)
from genie_flow.genie import GenieModel
from genie_flow.model.user import User


@inject
def store_session(
    session_model: GenieModel,
    mongo_store=Provide[GenieFlowPermanentPersistenceContainer.mongo_store],
    compression=Provide[
        GenieFlowPermanentPersistenceContainer.config.object_store.object_compression
    ]
    or True,
):
    col = mongo_store["genie_db"].session_collection
    if col.find_one({"session_id": session_model.session_id}) is None:
        result = col.insert_one(
            {
                "session_id": session_model.session_id,
                "model": session_model.serialize(compression),
            }
        )
    else:
        result = col.replace_one(
            {"session_id": session_model.session_id},
            {
                "session_id": session_model.session_id,
                "model": session_model.serialize(compression),
            },
            True,
        )

    logger.debug(
        "Successfully updated mongodb: {mongo_result}", mongo_result=result.acknowledged
    )


@inject
def store_user(
    user_info: User,
    session_id: str,
    mongo_store: MongoClient = Provide[
        GenieFlowPermanentPersistenceContainer.mongo_store
    ],
):
    col = mongo_store["genie_db"].user_collection
    if col.find_one({"email": user_info.email}) is None:
        logger.debug(user_info)
        result = col.insert_one(
            {
                "email": user_info.email,
                "firstname": user_info.firstname,
                "lastname": user_info.lastname,
                "custom_properties": user_info.custom_properties,
                "sessions": [session_id],
            }
        )
    else:
        logger.debug(user_info)
        result = col.update_one(
            {"email": user_info.email}, {"$addToSet": {"sessions": session_id}}, True
        )
    logger.debug(
        "Successfully updated mongodb: {mongo_result}", mongo_result=result.acknowledged
    )


@inject
def retrieve_user_sessions_mongo(
    user_info: User,
    mongo_store: MongoClient = Provide[
        GenieFlowPermanentPersistenceContainer.mongo_store
    ],
):
    col = mongo_store["genie_db"].user_collection
    user_email = user_info.email
    result = col.find_one({"email": user_email}, {"_id": 0})
    logger.debug("retrieved user sessions {result}", result=result)
    return result


@inject
def retrieve_model(
    session_id: str,
    mongo_store: MongoClient = Provide[
        GenieFlowPermanentPersistenceContainer.mongo_store
    ],
) -> dict[str, bytes] | None:
    col = mongo_store["genie_db"].session_collection
    payload = col.find_one({"session_id": session_id}, {"model": 1, "_id": 0})
    if payload is None:
        raise KeyError(f"No model with id {session_id}")
    return payload
