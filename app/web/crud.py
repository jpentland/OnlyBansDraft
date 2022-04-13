import asyncpg

class DB:
    @classmethod
    async def connect(cls, dbuser, dbpass, dbhost, dbport, dbname):
        db = cls()
        db.pool = await asyncpg.create_pool(
            user=dbuser,
            password=dbpass,
            host=dbhost,
            port=dbport,
            database=dbname,
        )

        return db

    async def close(self):
        await self.pool.close()

    async def check(self):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT 1")

        return "OK"
