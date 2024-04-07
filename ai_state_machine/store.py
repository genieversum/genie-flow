from pydantic_redis import Model, Store, RedisConfig

STORE = Store(
    name="genie", redis_config=RedisConfig(), life_span_in_seconds=86400
)
