<?php
// Wallos PHP built-in server router
// Replicates nginx try_files + security deny rules from nginx.conf / nginx.default.conf

$uri = $_SERVER['REQUEST_URI'];
$path = __DIR__ . DIRECTORY_SEPARATOR . ltrim($uri, '/');

// Deny direct .db access
if (preg_match('/\.db$/i', $uri)) {
    http_response_code(403);
    die('Forbidden');
}

// Deny PHP execution inside logos uploads dir
if (preg_match('#^/images/uploads/logos/.*\.php$#i', $uri)) {
    http_response_code(403);
    die('Forbidden');
}

// Deny .tmp/ directory entirely
if (strpos($uri, '/.tmp/') === 0 || strpos($uri, '/.tmp\\') === 0) {
    http_response_code(403);
    die('Forbidden');
}

// Deny includes/*.php
if (preg_match('#^/includes/.*\.php$#i', $uri)) {
    http_response_code(403);
    die('Forbidden');
}

// try_files behaviour:
// 1. Serve the file if it exists on disk
// 2. Fall back to index.php with query string
if (is_file($path) && !$uri === '/') {
    // Let PHP serve it natively
    return false;
}

// Route all other requests through index.php (frontend router)
$_SERVER['SCRIPT_NAME'] = '/index.php';
$_SERVER['PHP_SELF']    = '/index.php';
return false;
