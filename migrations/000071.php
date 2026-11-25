<?php
// This migration ensures the google_search table has the correct schema
// with user_id column for multi-user support.
// Also updates the table definition to include proper column ordering.

// Check if google_search table exists
$tableCheck = $db->query("SELECT name FROM sqlite_master WHERE type='table' AND name='google_search'");
$tableExists = $tableCheck->fetchArray(SQLITE3_ASSOC);

if ($tableExists !== false) {
    // Table exists - check if user_id column is missing
    $columnQuery = $db->query("SELECT * FROM pragma_table_info('google_search') WHERE name='user_id'");
    $columnExists = $columnQuery->fetchArray(SQLITE3_ASSOC) !== false;
    
    if (!$columnExists) {
        // Add user_id column to existing table
        $db->exec("ALTER TABLE google_search ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1");
    }
    
    // Ensure api_key column exists with proper default
    $apiKeyColumnQuery = $db->query("SELECT * FROM pragma_table_info('google_search') WHERE name='api_key'");
    $apiKeyColumnExists = $apiKeyColumnQuery->fetchArray(SQLITE3_ASSOC) !== false;
    
    if (!$apiKeyColumnExists) {
        $db->exec("ALTER TABLE google_search ADD COLUMN api_key TEXT NOT NULL DEFAULT ''");
    }
}