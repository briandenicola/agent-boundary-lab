# 04: Identity

Signing in to the harness and being allowed to read policy are separate decisions.

```text
Browser sign-in -> harness exchanges token on behalf of user
  -> bridge -> Foundry tool -> policy API validates token and checks user
```

## Try both users

1. Open the HTTPS harness as the allowed test user.
2. Ask for the servicing policy. Expect HTTP 200 and `allowed` with verified identity.
3. Repeat in a private browser as the denied user. Expect `403 user_not_authorized`.

Both users call the same tool and API. The display alias changes no permissions.
The policy token is request-scoped and is never sent to the test receiver.

## Read the result

| Result | Meaning |
| --- | --- |
| 200 with verified identity | Authorized |
| 401 | Token missing or invalid |
| 403 `user_not_authorized` | Authenticated user is not allowed |
| Missing token/identity evidence | Not a completed allowed/denied test |

None of these results establishes network containment.
[Full identity flow](../token-flow-documented.md)

For HTTPS/sign-in setup, use the [deployment guide](../rebuild-runbook.md#3-set-up-https-and-user-sign-in).

**Next:** [05: Agent and tools](05-agent-and-tools.md)
