# Third-party reference notices

Some offline canonicalization regression inputs in
`backend/tests/test_safe_browsing_urls.py` are adapted from the Google Safe
Browsing Go reference test vectors. The Python implementation is written for
this project; it is not the Go client or a Google-endorsed product.

Copyright 2016 Google Inc. All Rights Reserved.

Source: https://github.com/google/safebrowsing/blob/bbf0d20d26b32d99fd21664677fe31ee9f0f66e3/urls_test.go

Licensed under the Apache License, Version 2.0 (the "License"); you may not use
these adapted portions except in compliance with the License. The full license
is included at [licenses/Apache-2.0.txt](licenses/Apache-2.0.txt).

Unless required by applicable law or agreed to in writing, software distributed
under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.

## Optional model weights (not included in this repository)

The optional server model selected on 2026-11-24 (`koelectra-small-ft-v1`,
`docs/MODEL_POLICY.md`) is a fine-tuned copy of the encoder below, kept in a
local folder outside the repository. No model weights are committed here.

- `monologg/koelectra-small-v3-discriminator` (source repository
  monologg/KoELECTRA), Apache License 2.0 as confirmed by the user from the
  original repository on 2026-11-17. The downloaded files contained no model
  card. Full license text: [licenses/Apache-2.0.txt](licenses/Apache-2.0.txt).

Encoders compared but not selected: `intfloat/multilingual-e5-small` (model
card `license: mit`), `skt/kobert-base-v1` (Apache License 2.0 per the
SKTBrain/KoBERT GitHub repository; the model card states no license).
