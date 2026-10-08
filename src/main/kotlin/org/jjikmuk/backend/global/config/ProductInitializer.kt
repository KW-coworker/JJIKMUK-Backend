package org.jjikmuk.backend.global.config

import org.springframework.boot.CommandLineRunner
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.annotation.Order

/**
 * Product data work is opt-in. Normal API startup never reads the 891 MiB CSV.
 * Run it in a non-web process with the product-import or product-rollback profile.
 */
@Configuration(proxyBeanMethods = false)
class ProductInitializer {
    @Bean
    @Order(0)
    @ConditionalOnProperty(prefix = "product.import", name = ["enabled"], havingValue = "true")
    fun importProducts(productDataImportService: ProductDataImportService): CommandLineRunner =
        CommandLineRunner { productDataImportService.importProducts() }

    @Bean
    @Order(0)
    @ConditionalOnProperty(prefix = "product.import.rollback", name = ["enabled"], havingValue = "true")
    fun rollbackProducts(productDataImportService: ProductDataImportService): CommandLineRunner =
        CommandLineRunner { productDataImportService.rollbackProducts() }
}
