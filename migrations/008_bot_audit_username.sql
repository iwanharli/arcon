-- Catat identitas pencari dari bot Telegram: username & nama, bukan cuma id.
ALTER TABLE bot_audit ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE bot_audit ADD COLUMN IF NOT EXISTS name TEXT;
