from hub.telegram.types import BotIdentity, Member, ProviderError, TrustedEvent

BOT_ID = 9000001
BOT_USERNAME = "hub_dedicated_test_bot"


class FakeTelegram:
    def __init__(self):
        self.identity = BotIdentity(BOT_ID, BOT_USERNAME)
        self.webhook = False
        self.members: dict[tuple[int, int], Member] = {}
        self.events: list[TrustedEvent] = []
        self.schedule_sent = []
        self.callbacks = []
        self.sent: list[tuple[int, str]] = []
        self.offsets: list[int | None] = []
        self.send_error: ProviderError | None = None
        self.member_error: ProviderError | None = None
        self.poll_error: ProviderError | None = None
        self.initialized = False
        self.closed = False

    async def initialize(self):
        self.initialized = True
        return self.identity

    async def webhook_configured(self):
        return self.webhook

    async def updates(self, offset):
        self.offsets.append(offset)
        if self.poll_error:
            raise self.poll_error
        return [event for event in self.events if offset is None or event.update_id >= offset]

    async def member(self, chat_id, user_id):
        if self.member_error:
            raise self.member_error
        return self.members.get((chat_id, user_id), Member("left"))

    async def send(self, chat_id, message):
        if self.send_error:
            raise self.send_error
        self.sent.append((chat_id, message))
        return len(self.sent)

    async def send_schedule(self, chat_id, message, callback_data):
        result = await self.send(chat_id, message)
        self.schedule_sent.append((chat_id, message, callback_data))
        return result

    async def answer_callback(self, query_id, message):
        self.callbacks.append((query_id, message))

    async def close(self):
        self.closed = True

    def group(self, chat_id: int, actor: int, technician: int):
        self.members[(chat_id, BOT_ID)] = Member("administrator")
        self.members[(chat_id, actor)] = Member("administrator")
        self.members[(chat_id, technician)] = (
            Member("member") if actor != technician else Member("administrator")
        )
