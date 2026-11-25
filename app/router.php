<?php
// Wallos PHP built-in server router
// Serves from WALLOS_ROOT with security rules matching nginx.conf / nginx.default.conf
// __DIR__ is the app/ folder; WALLOS_ROOT is one level up

$uri   = $_SERVER['REQUEST_URI'] ?? '/';
$root  = dirname(__DIR__);          // WALLOS_ROOT (parent of app/)
$path  = $root . DIRECTORY_SEPARATOR . ltrim($uri, '/');

/* Security: block .db access anywhere */
if (preg_match('/\.db$/i', $path)) {
    http_response_code(403);
    die('Forbidden');
}
 
/* Security: block PHP in logo uploads */
if (stripos($uri, '/images/uploads/logos/') !== false && preg_match('/\.php$/i', $uri)) {
    http_response_code(403);
    die('Forbidden');
}
 
/* Security: block .tmp/ entirely */
if (strpos($uri, '/.tmp/') === 0 || strpos($uri, '/.tmp\\') === 0) {
    http_response_code(403);
    die('Forbidden');
}
 
/* Security: block direct access to includes/*.php */
if (preg_match('#^/includes/.*\.php$#i', $uri)) {
    http_response_code(403);
    die('Forbidden');
}
 
// try_files logic:
// // If request is a real file/directory on disk, let PHP serve it natively
if (is_file($path)) {
    return false;  // Let PHP serve it directly
}
 
// Fall back to index.php for all other requests (frontend router)
$_SERVER['SCRIPT_NAME'] = '/index.php';
$_SERVER['PHP_SELF']    = '/index.php';
return false;