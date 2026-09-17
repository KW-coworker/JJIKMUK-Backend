package org.jjikmuk.backend.domain.config

import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.stereotype.Repository

@Repository
interface SystemConfigRepository : JpaRepository<SystemConfig, String>