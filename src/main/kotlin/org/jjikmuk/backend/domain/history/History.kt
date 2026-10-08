package org.jjikmuk.backend.domain.history

import jakarta.persistence.*
import org.jjikmuk.backend.domain.user.User
import java.time.LocalDateTime

enum class UserActionType(
    val preferenceWeight: Double,
    val explicitPreference: Boolean,
    private val recordable: Boolean = true
) {
    SCAN(0.25, false),
    DETAIL_VIEW(0.50, false),
    SEARCH_CLICK(1.00, false),
    FAVORITE(3.00, true),
    EAT(2.50, true),
    DISLIKE(-3.00, true),
    OTHER(0.0, false, false);

    companion object {
        fun fromRequest(value: String): UserActionType? = entries.firstOrNull {
            it.recordable && it.name.equals(value.trim(), ignoreCase = true)
        }

        fun fromStored(value: String?): UserActionType = entries.firstOrNull {
            it.name.equals(value?.trim(), ignoreCase = true)
        } ?: OTHER

        fun supportedValues(): List<String> = entries.filter { it.recordable }.map(UserActionType::name)
    }
}

@Converter
class UserActionTypeConverter : AttributeConverter<UserActionType, String> {
    override fun convertToDatabaseColumn(attribute: UserActionType?): String =
        (attribute ?: UserActionType.OTHER).name

    override fun convertToEntityAttribute(dbData: String?): UserActionType =
        UserActionType.fromStored(dbData)
}

@Entity
@Table(name = "histories")
class History(
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    val id: Long? = null,

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    val user: User,

    @Column(nullable = false)
    val barcode: String, // 16.csv와 연결할 핵심 키

    @Convert(converter = UserActionTypeConverter::class)
    @Column(nullable = false, length = 32)
    val actionType: UserActionType,

    @Column(nullable = false)
    val createdAt: LocalDateTime = LocalDateTime.now()
)
