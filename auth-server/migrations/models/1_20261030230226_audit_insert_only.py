from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE FUNCTION audit_logs_insert_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is insert only';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER audit_logs_no_change
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION audit_logs_insert_only();

        CREATE TRIGGER audit_logs_no_truncate
            BEFORE TRUNCATE ON audit_logs
            FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_insert_only();
        """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TRIGGER audit_logs_no_truncate ON audit_logs;
        DROP TRIGGER audit_logs_no_change ON audit_logs;
        DROP FUNCTION audit_logs_insert_only();
        """


MODELS_STATE = (
    "eJztXW1v2zYQ/iuEv6wDuiBVnJcNwwA7cdusSVzEzla0GQRaYmQtsqiSVNKgy38fSUnWuy"
    "0nkmOr/NImRx5FPqSOz92RyvfODJvIoTs9RGxj2vkNfO+4cIb4D5mS16ADPS+WCwGDE0dW"
    "hXGdCWUEGoxLb6BDEReZiBrE9piNXS51fccRQmzwirZrxSLftb/6SGfYQmyKCC/48g8X26"
    "6JviEa/erd6jc2csxUV21TPFvKdfbgSdmpy97KiuJpE93Ajj9z48reA5tid17bdpmQWshF"
    "BDIkmmfEF90XvQvHGY0o6GlcJehiQsdEN9B3WGK4Ez2WdXT9YjjWR4OxrndWAMjArgCXd5"
    "XK0VuiC79ob7qH3aO9g+4RryK7OZccPgaPjoEJFCU8F+POoyyHDAY1JMYxqHeIUNGlHLLH"
    "U0iKoU2oZPDlHc/iG6G5COBIECMcr6p1QDyD33QHuRYTr4a2v78A0L96l8fve5eveK2fxS"
    "Mxfw2Ct+MiLNKCMoF6jLJ4qVZAOKzeQnTf7O5WQJfXKkVXlqXR5U9kKHi10wj/ORpeFCOc"
    "UMmgbNoGA/8Bx6Y5W7EFaC8AV4AhWp5R+tVJYvrqvPcpC/fx2bAvwcGUWUS2Ihvoc+iFgb"
    "65TVgTIZhA4/YeElPPlWANl9XNF820WVYCXWhJIMWIxfiiLcvzHNuAIUL5HS1RvHhbiytS"
    "tbm1anO7RQ+rmN2wej1m92WBTRndPa2Czd3TSk2uKEpbXPn/CshG9du4o2lHVXY07ah8Rx"
    "NlaXyTPcvBPEbfSuxCRu1JaIfLdFPAXoDtePBpvHhDmz2EJWfDi3dR9ewul0bepjq3/fZd"
    "wfLuY+wg6JaY5KReBvgJV2xqnUdWZb3Q94fDsxT0/dMstlfn/QFf93IeeCWboaTNjgH3EJ"
    "npM+jppZ5I6TZYpLp8U6wL+TcbvSkm2DFBYuQ6LCDIJ7yE2TNUQpJTmlmeHKruRD9soyXn"
    "AzSHrvMQvkiLjM3p+WA07p1/TC37k954IEq0lLWJpK8OMjZ/3gj4+3T8HohfwefhxSDLtO"
    "f1xp87ok/QZ1h38b0OzQSTiKQRaqlZ9z3zibOe1lSzvimzHmGUmHbZ+xXcsbTVtSmNfJ7M"
    "Rhcqv/1wiRxYwiZCN+vjvKEtXAmP0dqPpPGKiKEifNd/JkiXvIm2wuNTRHTK+KieCdIVb4"
    "g77SPRVJvAajQG4ps2O8NWpygAEpW9Xhj9ELV0B1vVYh+cjPFpYgBz87kDekC43hNIER+q"
    "bVmIAIL+RQaj4OqjsIcAuiY4GZwNxoOdTgbGZzR17V674ykCAUoAEgQ8h2MO7qDjIwr4sp"
    "nyBtgUuuAGE2RbLuDOPX0NKAaQN2xgYgIDuj8xMEHXLnQYIsgEmACHG2SuSLBvTXlVgzdh"
    "8S5hLkOA4HtgMxBAMkFUjml50OdLFNBNECpehYsNhkm2YKUQUd+2fpQo0a+atrd3qO3uHR"
    "ztdw8P949258w4X7SIIvdP3wmWnNqjl8eS5nNVOYgfKbQw6HHQrRDzOOiWhjxEUSZDYhQH"
    "Oxbi294sVP0AM0i4gVoF4FijDYGkNUTt1pjl22hw6483m4hB2ykgmOUZvoTKszJ8G4b0Oh"
    "J8qXjoSkvabumK7lY5E9AtPxLQzZ0IUFG5cui3Mz5TFpXbkHR5IlBT4Cymwzjl7mImblRv"
    "rlz6SXrgthj82aGTNJdN7NA9Ugn1F0qoy1lZYT+I6reQoau8b6vyvsK25BAfzaDjlBqNUG"
    "V9GcfmDceedngwtxnil0XmYnTeOzvL5xsJ5x3kScwmrVkDs9miNb1BRKYg0ZTPLyr+Wv4u"
    "tYu/qqxym2e9LKuciWvpK9HpWKFNm+OzWHXOC1wSNnwbpK0+oAcJ8SnvEHSNIjJdfN55yy"
    "Auy55yMYH3c/cusbI4AnzcKDhWdtwbHfdOBp3HKmcfakrot/PkQ5MhCHkMoiD4EB2PKA87"
    "zKesuYCD7JOKLrxkdEGdKm8w/6dCCy8VWlCuUvmi307SrFylH3HWlaukXKUNgHidrlJtx8"
    "Tb6zBlz0LXcAq6bcfFm/YpF6e280tvsZ+pN5zjls8ITf78SUKgnM8XTW0rlt4yvlaFpaff"
    "wOpvVU5PsbeCq6cJU1cR16RxVIgu5cMkZArPJMQtIxxZJpxYVMVUuNgi1ABsKylvFt6cLV"
    "zV32iSH6ZuFRaww+ytw3JuKC86Cqcqvuy4/LqcuKXG8C1ywbX4btp1BxgOtGc7YGRgD5mA"
    "Ywd4m/JiGnaR+PknGt06cxC8QzS4eYYoA9DhVfL36Bp6RiF5lSAEsxz6l4q1buTn+0qRfZ"
    "FvZexuNLwqfNcUnglzURHQhIZCdDkBFHDVwFOuwma2DNyqDCWxqJYTQBVjXkeMuWnOV3bW"
    "JBlfXcL1Gjt0kliOkWuiWJSK/W2kJWhx7E9FpxTd20REFd1bJ91TIdRaQqgvx/TKWN5yhq"
    "c+990uGuf5E+5zFW5AV1enJyWZvKRSBmPft80dofqUN3s51J3fb3xXfsUIyCeJf7p/dJp9"
    "1YugDT7IElCxJMmSQ89v8aue007qtO7j6vWf1EYzaDur4DtXqOV09gZhq+1XAZfXWvC3WH"
    "Lw3tiEMn3VNZzWasMx+KaXsQOfAHNKSaG8HGUPUnqPOY+aQjrNI11+sSOn2IpbNOu+26H+"
    "XMCa/1wAB476HiLFnvAyzFOqa4R9Ltla3FWItNzEtzdEqi4xtW3Wyy4x5YKOVa6HpE9DPe"
    "/SQxs//V7znxFQd0NeV4gOPv4PEZ8rdw=="
)
