package org.jjikmuk.backend.domain.user

import jakarta.persistence.*
import com.fasterxml.jackson.annotation.JsonIgnore

enum class UserRole {
    USER, ADMIN
}

enum class AuthProvider {
    LOCAL,
    GOOGLE,
    LOCAL_AND_GOOGLE;

    val supportsPassword: Boolean
        get() = this == LOCAL || this == LOCAL_AND_GOOGLE

    fun linkGoogle(): AuthProvider = when (this) {
        LOCAL -> LOCAL_AND_GOOGLE
        GOOGLE, LOCAL_AND_GOOGLE -> this
    }
}

@Entity
@Table(name = "users")
class User(
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    val id: Long? = null,

    @Column(nullable = false, unique = true)
    val email: String,

    @Column(nullable = false, unique = true)
    var nickname: String,

    @Column(length = 1000)
    var allergies: String? = null,

    @Column(length = 1000)
    var diseases: String? = null,

    @JsonIgnore
    @Column(nullable = false)
    var password: String,

    @Enumerated(EnumType.STRING)
    var role: UserRole = UserRole.USER,

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    var authProvider: AuthProvider = AuthProvider.LOCAL,

    @Column(nullable = false)
    var profileCompleted: Boolean = true,

    @Column(nullable = false)
    var tokenVersion: Int = 0,

    @Column(length = 1000)
    var specialDiet: String? = null,

    @Column(length = 1000)
    var dislikedIngredients: String? = null
){
    fun updateProfile(
        nickname: String,
        allergies: String?,
        diseases: String?,
        specialDiet: String?,
        dislikedIngredients: String?
    ) {
        this.nickname = nickname
        this.allergies = allergies
        this.diseases = diseases
        this.specialDiet = specialDiet
        this.dislikedIngredients = dislikedIngredients
        this.profileCompleted = true
    }

    fun invalidateSessions() {
        tokenVersion += 1
    }
}
