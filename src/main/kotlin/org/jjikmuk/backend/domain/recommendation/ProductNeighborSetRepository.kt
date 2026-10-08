package org.jjikmuk.backend.domain.recommendation

import org.springframework.data.jpa.repository.JpaRepository

interface ProductNeighborSetRepository : JpaRepository<ProductNeighborSet, String>
