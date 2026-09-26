# Third-party services

Pixeldeck works entirely offline through its local engines. The providers
below are optional: they register themselves only when their section in
`config.json` has credentials, and a tool is only ever sent an image when you
pick that tool from a menu.

When you do, the image (and the mask, for the tools that take one) is uploaded
to that provider and the result is downloaded back. Their terms and their
privacy policies apply to that request.

| provider | section in `config.json` | endpoint | used for |
| --- | --- | --- | --- |
| Google Gemini | `gemini` | `generativelanguage.googleapis.com` | AI Edit |
| [OI] | `openai` | `api.openai.com` | AI Edit |
| [AILabTools] | `ailabtools` | `www.ailabapi.com` | Super Resolution, Inpainting, Background Removal |
| [Pixian.AI] | `pixian` | `api.pixian.ai` | Background Removal |
| [Replicate] | `replicate` | `api.replicate.com` | Super Resolution, Background Removal, Enhance |

The keys are read from `config.json` for each request and are only sent to the
provider they belong to, as an `Authorization` or `x-api-key` header. Nothing
is sent anywhere else, and the web UI never receives a key back: the Config
dialog shows whether one is set, not what it is.
