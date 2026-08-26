# Pull Request 규칙

Pull Request는 `develop`을 대상으로 하며 Conventional Commits 형식의 제목을 사용한다.
`type(scope)`는 영문 식별자를 유지하고 제목의 subject는 한국어를 기본으로 작성한다.
각 PR은 하나의 Issue만 다루며 다음 내용을 포함한다.

- `Closes #N`
- background and scope
- notable design decisions
- verification results
- impact and excluded scope
- completed checklist from the pull request template

사용자에게 표시되는 제목과 본문은 한국어를 기본으로 작성한다. 코드 식별자, 경로,
API 경로, 외부 프로젝트명, 로그·명령어는 정확성을 위해 원문을 유지할 수 있다.
GitHub API나 CLI로 본문을 등록할 때도 UTF-8을 유지하며, 인코딩 변환으로 `?`, `??`,
`U+FFFD` 또는 의미 없는 대체 문자가 포함된 본문은 제출하지 않는다.

The author is the assignee when the repository supports it. Reviewer automation is
optional and must not conceal permission or assignment failures. Pull requests to
`main` require explicit user approval and are never automatically merged.
