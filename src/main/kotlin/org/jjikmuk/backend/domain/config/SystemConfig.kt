package org.jjikmuk.backend.domain.config

import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.Id
import jakarta.persistence.Table
import java.time.LocalDateTime

@Entity
@Table(name = "system_configs")
class SystemConfig(
    @Id
    @Column(name = "config_key")
    val configKey: String,

    @Column(name = "config_value")
    var configValue: String,

    @Column(name = "updated_at")
    var updatedAt: LocalDateTime = LocalDateTime.now()
) {
    fun updateVersion(newVersion: String) {
        this.configValue = newVersion
        this.updatedAt = LocalDateTime.now()
    }
}