from pydantic_redis import Model, Store, RedisConfig

STORE = Store(
    name="genie", redis_config=RedisConfig(), life_span_in_seconds=86400
)


def get_single_model(cls: type[Model], unique_id: str) -> Model:
    models = cls.select(ids=[unique_id])
    assert len(models) == 1

    return models[0]