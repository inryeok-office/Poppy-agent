# Contributing

## Workflow

1. Confirm the approved Issue and its completion conditions.
2. Update from the latest `develop`.
3. Create `feature/`, `fix/`, `refactor/`, `chore/`, or `docs/` work in an Issue-specific branch.
4. Keep the change within the Issue scope and preserve existing user changes.
5. Run the full local verification suite.
6. Open a pull request targeting `develop` and link the Issue with `Closes #N`.
7. Merge only after CI and review requirements pass, using squash merge.

Do not commit directly to `main` or `develop`. Do not add speculative APIs, unused
abstractions, or unrelated formatting changes. The physical robot safety boundary in
`AGENTS.md` applies to every contribution.

## 커밋 메시지와 GitHub 문서 언어

Conventional Commits를 사용한다. `type(scope)`는 영문 식별자를 사용하고 subject는
한국어를 기본으로 작성한다. 예시는 `chore(init): 개발 환경 구성`과 같다.
제품명, API명, 라이브러리명, 코드 식별자, 명령어처럼 원문이 필요한 용어는 그대로
사용할 수 있다. subject는 간결하고 작업명 중심으로 작성하며 마침표를 붙이지 않는다.

Issue 제목·본문, PR 제목·본문, 리뷰 설명과 개발 문서는 한국어를 기본으로 작성한다.
외부 도구가 요구하는 키워드(`Closes #N`, Conventional Commit type/scope 등)와
코드·경로·로그는 원문을 유지한다.

모든 저장소 텍스트 파일은 UTF-8로 저장한다. GitHub 본문을 CLI/API로 등록할 때
Windows 로컬 코드 페이지로 변환하지 않으며, 본문에 `?`, `??`, `U+FFFD` 같은 인코딩
대체 문자가 남지 않았는지 확인한다.
