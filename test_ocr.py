#!/usr/bin/env python3
"""Pillar 4 OCR verification using Apple Silicon Vision ANE."""
import time
from Quartz import (
    CGRectNull,
    CGWindowListCreateImage,
    kCGWindowListOptionOnScreenOnly,
    kCGNullWindowID,
    kCGWindowImageDefault
)
import Vision

img = CGWindowListCreateImage(CGRectNull, kCGWindowListOptionOnScreenOnly, kCGNullWindowID, kCGWindowImageDefault)
req = Vision.VNRecognizeTextRequest.alloc().init()
h = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
t0 = time.time()
ok, err = h.performRequests_error_([req], None)
lines = [o.topCandidates_(1)[0].string() for o in (req.results() or []) if o.topCandidates_(1)]
print(f"OCR ok: {ok} | {len(lines)} lines detected in {time.time()-t0:.2f}s")
if lines:
    print("Sample:", " | ".join(lines[:3])[:120])
