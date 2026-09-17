import type { TelegramState } from "@hub/contracts";
export const disconnected = {
  state: "NOT_CONNECTED",
  approved: false,
  generation: 0,
  availability: "UNKNOWN",
  telegram_id: null,
  display_name: null,
  username: null,
  replacement_pending: false,
  invitation: null,
};
export const telegramState: TelegramState = {
  private: { ...disconnected },
  group: { ...disconnected },
  runtime: {
    mode: "fake",
    state: "RUNNING",
    bot_username: "hub_dedicated_test_bot",
    heartbeat_at: null,
    error_code: null,
  },
  deliveries: [],
};
