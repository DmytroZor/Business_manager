from core.db import engine
from routers import product_router, user_router, address_router, order_router
from fastapi import FastAPI
from core import models
app = FastAPI()


async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


@app.on_event("startup")
async def on_startup():
    await init_models()


app.include_router(product_router.router)
app.include_router(user_router.router)
app.include_router(address_router.router)
app.include_router(order_router.router)
