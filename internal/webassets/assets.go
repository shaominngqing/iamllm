package webassets

import "embed"

// Dist is generated from the React application in /web.
//
//go:embed all:dist
var Dist embed.FS
