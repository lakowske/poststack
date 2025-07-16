-- Rollback: Add User Creation Notify (Unified Project Scenario)
-- This removes all notification functions and triggers

DROP TRIGGER IF EXISTS trigger_notify_user_created ON unified.users;
DROP TRIGGER IF EXISTS trigger_notify_user_updated ON unified.users;
DROP TRIGGER IF EXISTS trigger_notify_user_deleted ON unified.users;

DROP FUNCTION IF EXISTS unified.notify_user_created();
DROP FUNCTION IF EXISTS unified.notify_user_updated();
DROP FUNCTION IF EXISTS unified.notify_user_deleted();

DROP TABLE IF EXISTS unified.mailbox_events;