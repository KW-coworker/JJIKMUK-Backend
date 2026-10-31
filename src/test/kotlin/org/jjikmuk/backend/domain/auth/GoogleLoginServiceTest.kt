package org.jjikmuk.backend.domain.auth

import org.junit.jupiter.api.Test
import org.mockito.Mockito.*
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.dao.DuplicateKeyException
import java.sql.SQLException
import java.time.Instant
import kotlin.test.*

class GoogleLoginServiceTest {
    private val verifier = mock(GoogleIdentityVerifier::class.java)
    private val transactions = mock(GoogleLoginTransactions::class.java)
    private val service = GoogleLoginService(verifier, transactions)
    private val identity = GoogleIdentity("test-subject", "test@example.com")
    private val request = GoogleLoginRequest("verified-test-token")

    @Test fun `creation conflict recovers once using the already verified identity`() {
        val error = DataIntegrityViolationException("unique", SQLException("test", "23505"))
        val result = GoogleLinkRequiredResponse(linkToken = "test-proof", expiresAt = Instant.now())
        `when`(verifier.verify(request.idToken)).thenReturn(identity)
        `when`(transactions.loginOrCreate(identity)).thenThrow(GoogleAccountCreationConflict(error))
        `when`(transactions.recoverExisting(identity)).thenReturn(result)
        assertSame(result, service.login(request))
        val order = inOrder(verifier, transactions)
        order.verify(verifier).verify(request.idToken)
        order.verify(transactions).loginOrCreate(identity)
        order.verify(transactions).recoverExisting(identity)
        verifyNoMoreInteractions(verifier, transactions)
    }

    @Test fun `no matching identity after collision propagates original failure without inserting again`() {
        val error = DataIntegrityViolationException("unrelated nickname conflict", SQLException("test", "23505"))
        `when`(verifier.verify(request.idToken)).thenReturn(identity)
        `when`(transactions.loginOrCreate(identity)).thenThrow(GoogleAccountCreationConflict(error))
        `when`(transactions.recoverExisting(identity)).thenReturn(null)
        assertSame(error, assertFailsWith<DataIntegrityViolationException> { service.login(request) })
        verify(transactions).loginOrCreate(identity)
        verify(transactions).recoverExisting(identity)
        verifyNoMoreInteractions(transactions)
    }

    @Test fun `session or other database failure does not trigger account recovery`() {
        val error = DataIntegrityViolationException("session unique failure", SQLException("test", "23505"))
        `when`(verifier.verify(request.idToken)).thenReturn(identity)
        `when`(transactions.loginOrCreate(identity)).thenThrow(error)
        assertSame(error, assertFailsWith<DataIntegrityViolationException> { service.login(request) })
        verify(transactions).loginOrCreate(identity)
        verifyNoMoreInteractions(transactions)
    }

    @Test fun `recovery failure is not retried indefinitely`() {
        val original = DataIntegrityViolationException("original unique failure")
        val recoveryFailure = IllegalStateException("test-only failure")
        `when`(verifier.verify(request.idToken)).thenReturn(identity)
        `when`(transactions.loginOrCreate(identity)).thenThrow(GoogleAccountCreationConflict(original))
        `when`(transactions.recoverExisting(identity)).thenThrow(recoveryFailure)
        assertSame(recoveryFailure, assertFailsWith<IllegalStateException> { service.login(request) })
        verify(transactions).loginOrCreate(identity)
        verify(transactions).recoverExisting(identity)
        verifyNoMoreInteractions(transactions)
    }

    @Test fun `unique detection accepts driver codes and rejects other integrity failures`() {
        assertTrue(isUniqueKeyViolation(DataIntegrityViolationException("h2 or postgres", SQLException("test", "23505"))))
        assertTrue(isUniqueKeyViolation(DataIntegrityViolationException("mysql", SQLException("test", "23000", 1062))))
        assertTrue(isUniqueKeyViolation(DuplicateKeyException("translated unique")))
        assertTrue(isUniqueKeyViolation(DataIntegrityViolationException("wrapped",
            RuntimeException(SQLException("test", "23505")))))
        assertFalse(isUniqueKeyViolation(DataIntegrityViolationException("mysql null", SQLException("test", "23000", 1048))))
        assertFalse(isUniqueKeyViolation(DataIntegrityViolationException("mysql fk", SQLException("test", "23000", 1452))))
        assertFalse(isUniqueKeyViolation(DataIntegrityViolationException("h2 check", SQLException("test", "23513"))))
        assertFalse(isUniqueKeyViolation(DataIntegrityViolationException("duplicate email message alone")))
    }
}
