from typing import List, Type

import coc
from aiocache import SimpleMemoryCache, cached
from coc import Clan, Location, Player
import asyncio
from typing import AsyncIterator, Iterable, Awaitable, Any

class CustomClashClient(coc.Client):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def get_player(
            self,
            player_tag: str,
            cls: Type[Player] = coc.Player,
            cache: bool = True,
            **kwargs
    ) -> Player:
        player_tag = player_tag.split('|')[-1]

        return await super().get_player(player_tag, cls, **kwargs)

    async def get_clan(
            self,
            tag: str,
            cls: Type[Clan] = coc.Clan,
            cache: bool = True,
            **kwargs
    ) -> Clan:
        tag = tag.split('|')[-1]

        return await super().get_clan(tag, cls, **kwargs)


    @cached(ttl=None, cache=SimpleMemoryCache)
    async def search_locations(
        self, *, limit: int = None, before: str = None, after: str = None, cls: Type[Location] = None, **kwargs
    ) -> List[Location]:
        return await super().search_locations(limit=limit, before=before, after=after, cls=cls, **kwargs)

    async def fetch_players(
        self,
        player_tags: list[str],
        cls: Type[Player] = coc.Player,
        **kwargs
    ) -> AsyncIterator[Player]:
        tasks = [self.get_player(player_tag=tag, cls=cls, **kwargs) for tag in player_tags]
        return self._run_tasks_stream(coros=tasks, return_exceptions=True)



    async def fetch_clans(
            self,
            clan_tags: list[str],
            cache: bool = True,
    ):
        # TODO: Implement batch clan fetching similar to fetch_players
        pass

    @staticmethod
    async def _run_tasks_stream(
        coros: Iterable[Awaitable[Any]], *, return_exceptions: bool = False
    ) -> AsyncIterator[Any]:

        batch_size = 100
        sem = asyncio.Semaphore(batch_size)

        async def run_with_sem(awaitable):
            async with sem:
                try:
                    return await awaitable
                except Exception as e:
                    if return_exceptions:
                        return e
                    raise

        def add_tasks_to_flight(coro_iter, in_flight_set, count):
            """Add up to 'count' tasks from iterator to in_flight set."""
            for _ in range(count):
                try:
                    next_coro = next(coro_iter)
                    in_flight_set.add(asyncio.create_task(run_with_sem(next_coro)))
                except StopIteration:
                    break

        it = iter(coros)
        in_flight: set[asyncio.Task] = set()

        # Prime up to concurrency
        try:
            add_tasks_to_flight(it, in_flight, batch_size)

            while in_flight:
                done, in_flight = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)

                # Yield all finished results
                for task in done:
                    yield task.result()  # may be an Exception if return_exceptions=True

                # Refill the window
                add_tasks_to_flight(it, in_flight, len(done))
        finally:
            # If caller breaks early, cancel the rest
            for task in in_flight:
                task.cancel()
            if in_flight:
                await asyncio.gather(*in_flight, return_exceptions=True)
