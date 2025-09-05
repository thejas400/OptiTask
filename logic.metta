; logic.metta

= (professional_keyword meeting) True
= (professional_keyword report) True
= (professional_keyword client) True
= (professional_keyword project) True
= (professional_keyword email) True

= (personal_keyword gym) True
= (personal_keyword grocery) True
= (personal_keyword family) True
= (personal_keyword birthday) True
= (personal_keyword call_mom) True

= (classify_task $Name "professional")
  (professional_keyword $Name)

= (classify_task $Name "personal")
  (personal_keyword $Name)

= (classify_task $Name "unknown") True
