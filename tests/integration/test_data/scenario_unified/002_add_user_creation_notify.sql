-- Description: Add User Creation Notify (Unified Project Scenario)
-- This adds notification functions and triggers for user creation

CREATE OR REPLACE FUNCTION unified.notify_user_created()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(
        'user_created',
        json_build_object(
            'user_id', NEW.id,
            'username', NEW.username,
            'email', NEW.email,
            'domain', NEW.domain,
            'created_at', NEW.created_at
        )::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION unified.notify_user_updated()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.email != OLD.email OR NEW.domain != OLD.domain THEN
        PERFORM pg_notify(
            'user_updated',
            json_build_object(
                'user_id', NEW.id,
                'username', NEW.username,
                'old_email', OLD.email,
                'new_email', NEW.email,
                'updated_at', NEW.updated_at
            )::text
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION unified.notify_user_deleted()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(
        'user_deleted',
        json_build_object(
            'user_id', OLD.id,
            'username', OLD.username,
            'email', OLD.email,
            'deleted_at', now()
        )::text
    );
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_notify_user_created
    AFTER INSERT ON unified.users
    FOR EACH ROW
    EXECUTE FUNCTION unified.notify_user_created();

CREATE TRIGGER trigger_notify_user_updated
    AFTER UPDATE ON unified.users
    FOR EACH ROW
    EXECUTE FUNCTION unified.notify_user_updated();

CREATE TRIGGER trigger_notify_user_deleted
    AFTER DELETE ON unified.users
    FOR EACH ROW
    EXECUTE FUNCTION unified.notify_user_deleted();

CREATE TABLE unified.mailbox_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    user_id INTEGER,
    username VARCHAR(255),
    email VARCHAR(255),
    domain VARCHAR(255),
    home_directory VARCHAR(500),
    event_data JSONB,
    processed BOOLEAN DEFAULT false,
    processed_at TIMESTAMP NULL,
    error_message TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);