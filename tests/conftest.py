import os
import random
import time
import uuid
from typing import Optional

import pytest
import redis
from loguru import logger
from pydantic import Field, computed_field

from genie_flow.genie import GenieModel
from genie_flow.model.dialogue import DialogueElement
from genie_flow.model.user import User
from genie_flow.model.versioned import VersionedModel
from genie_flow.session_lock import SessionLockManager


@pytest.fixture(scope="session")
def docker_compose_file():
    return "tests/resources/docker-compose.yaml"


@pytest.fixture(scope="session")
def docker_setup(docker_setup):
    if "REDIS_SERVER" in os.environ:
        return False
    return docker_setup


@pytest.fixture(scope="session")
def docker_cleanup(docker_cleanup):
    if "REDIS_SERVER" in os.environ:
        return False
    return docker_cleanup


@pytest.fixture(scope="session")
def redis_server_details(docker_services) -> Optional[dict[str, str | int]]:

    def redis_server_is_responsive(host, port, db):
        try:
            logger.info(
                "trying to reach Redis at host {host}, port {port} and database {db}",
                host=host,
                port=port,
                db=db,
            )
            connection = redis.Redis(host=host, port=port, db=db)
            connection.ping()
        except redis.exceptions.ConnectionError as e:
            logger.exception("failed to reach Redis", e)
            return False

        connection.close()
        return True

    def get_existing():
        host, port, db = (
            os.environ.get("REDIS_SERVER"),
            os.environ.get("REDIS_SERVER_PORT"),
            os.environ.get("REDIS_SERVER_DB"),
        )
        logger.info(
            "We are using an existing redis server at {redis_server}, "
            "port {redis_server_port} and redis database {redis_server_db}",
            redis_server=host,
            redis_server_port=port,
            redis_server_db=db,
        )

        for _ in range(900):
            if redis_server_is_responsive(host, port, db):
                return host, port, db
            time.sleep(0.1)

        logger.critical("failed to reach Redis Server in time -- giving up")
        raise ValueError("Failed to reach existing Redis server")

    if "REDIS_SERVER" in os.environ:
        host, port, db = get_existing()
    else:
        host, port, db = ("localhost", 6379, 0)
        logger.info("We are using a local docker container for redis")
        docker_services.wait_until_responsive(
            timeout=90.0,
            pause=0.1,
            check=lambda: redis_server_is_responsive(host, port, db)
        )

    return {
        "host": host,
        "port": port,
        "db": db,
    }

@pytest.fixture(scope="function")
def genie_model():
    return GenieModel(
        session_id=uuid.uuid4().hex,
        dialogue=[
            DialogueElement(
                actor=random.choice(["system", "assistant", "user"]),
                actor_text=" ".join(
                    random.choices(
                        [
                            "aap", "noot", "mies", "wim", "zus", "jet",
                            "teun", "vuur", "gijs", "lam", "kees", "bok",
                            "weide", "does", "hok", "duif", "schapen"
                        ],
                        k=32
                    )
                )
            )
            for _ in range(50)
        ]
    )


@pytest.fixture
def session_lock_manager_unconnected():
    return SessionLockManager(
        None,
        None,
        None,
        600,
        600,
        600,
        False,
        "genie-flow-test",
    )


@pytest.fixture
def session_lock_manager_connected(redis_server_details):
    connection = redis.Redis(**redis_server_details)
    return SessionLockManager(
        redis_object_store=connection,
        redis_lock_store=connection,
        redis_progress_store=connection,
        object_expiration_seconds=120,
        lock_expiration_seconds=120,
        progress_expiration_seconds=120,
        compression=False,
        application_prefix="genie-flow-test",
    )


@pytest.fixture
def user():
    return User(
        email="aap@noot.com",
        firstname="Aap",
        lastname="Noot",
        custom_properties={
            "GTM": "HLS"
        }
    )


class ComputedFieldsModel(VersionedModel):
    relevant_letters: list[str] = Field(
        default_factory=list,
        description="letters that are relevant",
    )
    relevant_digits: list[str] = Field(
        default_factory=list,
        description="digits that are relevant",
    )

    @computed_field
    @property
    def relevant_letters_digits(self) -> list[tuple[str, str]] :
        return [
            (letter, digit)
            for letter in self.relevant_letters
            for digit in self.relevant_digits
        ]


@pytest.fixture
def example_computed_field():
    return ComputedFieldsModel(
        relevant_letters=["a", "b", "c"],
        relevant_digits=["1", "2", "3"],
    )