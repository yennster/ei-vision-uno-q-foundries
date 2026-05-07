# ei-vision

Edge Impulse object-detection inference (coffee & lamp) for Arduino UNO Q,
sourced from EI project 25483.

The container runs `edge-impulse-linux-runner` against `object-detection.eim`,
streaming inference results on port 4912 (HTTP/WebSocket UI).

`app.yaml` is included for use with Arduino App Lab; the App Lab brick path
expects the model at `/home/arduino/.arduino-bricks/ei-models/object-detection.eim`.
