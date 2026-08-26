# 커밋 규칙

Conventional Commits 형식을 사용한다.

```text
type(scope): subject
```

Examples:

- `chore(init): 개발 환경 구성`
- `feat(agent): 에이전트 수명주기 기반 구성`
- `fix(server): heartbeat 재시도 처리`

`type`과 `scope`는 Conventional Commits 호환성을 위해 영문 식별자를 사용한다.
`subject`는 변경 내용을 설명하는 한국어를 기본으로 작성하며, 제품명·기술명·API명·
코드 식별자처럼 번역하면 의미가 달라지는 용어는 원문을 유지할 수 있다.

subject는 간결하고 작업명 중심으로 작성한다. `update`, `work`, `fix`처럼 의미가
불분명한 표현과 마침표는 사용하지 않는다. 기존 커밋 history는 이 정책을 위해
rewrite하지 않는다.
