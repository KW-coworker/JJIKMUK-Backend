package org.jjikmuk.backend.domain.user

import jakarta.persistence.*
import com.fasterxml.jackson.annotation.JsonIgnore

enum class UserRole {
    USER, ADMIN
}

@Entity
@Table(name = "users")
class User(
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    val id: Long? = null,

    @Column(nullable = false, unique = true)
    val email: String,

    @Column(nullable = false)
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

    var specialDiet: String? = null,
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
    }
}
