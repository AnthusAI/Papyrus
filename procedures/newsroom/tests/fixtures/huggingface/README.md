Recorded responses from https://huggingface.co/api/models on 2026-10-25 (the rows of one list page each, with the
`expand` fields the monitor requests). Tests replay them; no test touches the network. Only an over-long
license text in `cardData` was trimmed.

- `text-to-speech-newest.json`: `pipeline_tag=text-to-speech&sort=createdAt&direction=-1&limit=12`
- `nvidia-newest.json`: `author=nvidia&sort=createdAt&direction=-1&limit=3`
- `text-generation-most-liked.json`: `pipeline_tag=text-generation&sort=likes&direction=-1&limit=3`
