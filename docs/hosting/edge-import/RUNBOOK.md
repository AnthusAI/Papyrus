# p.apyr.us edge adoption (account 712236451410, us-east-1)

Step 1, import (template: p-apyr-us-edge-import.yaml in this folder):
resources to import:
- ReaderEdgeFunction -> FunctionName papyrus-reader-edge
- MarketingDistribution -> Id E17ZRAI87DN065
- ReaderDistribution -> Id E2EM0JLBC2W9WW

Parameters (use the live values): CertificateArn (the stack's current value), ReaderCertificateArn arn:aws:acm:us-east-1:712236451410:certificate/5daf7da4-bdc1-42fe-93c4-a4fe2f948805, MarketingCertificateArn arn:aws:acm:us-east-1:712236451410:certificate/6b83eeb4-ecde-4665-89f0-c480e7877ac4, AmplifyAppId ds6yswxui41yi. The template in this folder already contains the stack's own three resources plus the three adopted ones. ProductionDistribution keeps the aliases the stored stack template has, because an import change set may contain no other change; step 2 then drops them, matching the live distribution E2QW8WOFWQT0H4, which has none (they sit on E17ZRAI87DN065), so read that diff and expect no real change.

Step 2, update with docs/hosting/p-apyr-us-edge.yaml from AnthusAI/Papyrus develop (PR 350). Expected diff: ReaderEdgeFunction code, one function association on MarketingDistribution's default behavior. Nothing replaced.

Step 3, delete the function papyrus-legacy-reader-redirect (nothing references it afterwards).
