CREATE OR REPLACE VIEW ${database}.${view_name} AS
SELECT *
FROM ${database}.${table_name}
WHERE last_seen_at > current_timestamp - interval '${ttl_hours}' hour
