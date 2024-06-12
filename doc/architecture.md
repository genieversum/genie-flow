```mermaid
classDiagram
    GenieFlowContainer *-- GenieFlowPersistenceContainer
    GenieFlowAPIContainer *-- GenieFlowContainer
    GenieFlowCeleryContainer *-- GenieFlowContainer
    
    GenieFlowPersistenceContainer *-- StoreManager
    GenieFlowPersistenceContainer *-- SessionLockManager
    StoreManager *-- Store
    SessionLockManager *-- Redis
    Store *-- Redis
    
    class GenieFlowPersistenceContainer{
        config
        pydantic_redis_store
        redis_lock_store
        store_manager
        session_lock_manager
    }
    
    class GenieFlowContainer{
        config
        model_key_registry
        storage
        session_manager
        genie_environment
    }
    
    class GenieFlowAPIContainer{
        config
        genie_environment
        fastapi_app
    }
    
    class GenieFlowCeleryContainer{
        config
        genie_environment
        celery_app
    }
    
```